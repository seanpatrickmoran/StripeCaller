import os
import re
import numpy as np
from scipy.signal import find_peaks
from scipy.stats import kruskal, poisson
import matplotlib.pyplot as plt
from AVL_tree import AVLTree
from peak_utils import *

stats_log = []
_calculated_values = {}
_poisson_stats = {}

from multiprocessing import Pool, cpu_count
from functools import partial


def subsetNpMatrix(matrix, row_bounds, column_bounds):
    rows = np.array([x for x in range(row_bounds[0], row_bounds[1]) if 0 <= int(x) < matrix.shape[0]])
    cols = np.array([y for y in range(column_bounds[0], column_bounds[1]) if 0 <= int(y) < matrix.shape[1]])
    #     if rows.size==0 or cols.size==0:
    #         print("--------------")
    #         print(f"rows: {rows}")
    #         print(f"row_bounds: {row_bounds}")
    #         print(f"cols: {cols}")
    #         print(f"column_bounds: {column_bounds}")
    #         return "Empty"
    #     if row_bounds[0]>row_bounds[1]:
    #         print(f"rowbounds0 > rowbounds1, {row_bounds[0]}, {row_bounds[1]}")
    subset = (matrix.ravel()[(cols + (rows * matrix.shape[1]).reshape((-1, 1))).ravel()]).reshape(rows.size, cols.size)
    return subset


def hic2txt(hic_file, ch, resolution=1000, output='temp.txt'):
    """
    Dump .hic file into contact lists
    :param hic_file: (str) .hic file path
    :param ch: (str) chromosome
    :param resolution: (int) resolution to use
    :param output: (str) temporary output path
    """
    juicer = '/nfs/turbo/umms-drjieliu/juicer_tools_1.11.04_jcuda.0.8.jar'
    # cmd = f'java -jar {juicer} dump observed KR {hic_file} {ch} {ch} BP {resolution} {output}'
    cmd = f'java -jar {juicer} dump oe KR {hic_file} {ch} {ch} BP {resolution} {output}'
    os.system(cmd)


def load_chrom_sizes(reference_genome):
    """
    Load chromosome sizes for a reference genome
    """
    my_path = os.path.abspath(os.path.dirname(__file__))
    # rg_path = f'{my_path}/reference_genome/{reference_genome}'
    rg_path = f'{my_path}/{reference_genome}'
    f = open(rg_path)
    lengths = {}
    for line in f:
        [ch, l] = line.strip().split()
        lengths[ch] = int(l)
    return lengths


def txt2horizontal(txt, length, max_range, resolution=1000):
    """
        :param txt: str, path of input .txt file
        :param length: chromosome length
        :param max_range: int, max distance
        :param resolution: int, default: 25000
    """
    assert max_range % resolution == 0
    f = open(txt)
    n_bins = length // resolution + 1
    rg = max_range // resolution
    mat = np.zeros((n_bins, rg))
    cnt = 0
    for line in f:
        if cnt % 5000000 == 0:
            print('  Loading: ', cnt)
        cnt += 1
        p1, p2, v = line.strip().split()
        if v == 'NaN':
            continue
        p1, p2, v = int(p1), int(p2), float(v)
        if max(p1, p2) >= n_bins * resolution:
            continue
        if p1 > p2:
            p1, p2 = p2, p1
        p1, p2 = p1 // resolution, p2 // resolution
        if p2 - p1 >= rg:
            continue
        mat[p1, p2 - p1] += v
    return mat


def txt2vertical(txt, length, max_range, resolution=1000):
    """
         :param txt: str, path of input .txt file
         :param length: chromosome length
         :param max_range: int, max distance
         :param resolution: int, default: 25000
    """
    assert max_range % resolution == 0
    f = open(txt)
    n_bins = length // resolution + 1
    rg = max_range // resolution
    mat = np.zeros((n_bins, rg))
    cnt = 0
    for line in f:
        if cnt % 5000000 == 0:
            print('  Loading: ', cnt)
        cnt += 1
        p1, p2, v = line.strip().split()
        if v == 'NaN':
            continue
        p1, p2, v = int(p1), int(p2), float(v)
        if max(p1, p2) >= n_bins * resolution:
            continue
        if p1 > p2:
            p1, p2 = p2, p1
        p1, p2 = p1 // resolution, p2 // resolution
        if p2 - p1 >= rg:
            continue
        mat[p2, p2 - p1] += v
    return mat


def txt2mat(txt, length, max_range, resolution=1000):
    """
        :param txt: str, path of input .txt file
        :param length: chromosome length
        :param max_range: int, max distance
        :param resolution: int, default: 25000
    """
    assert max_range % resolution == 0
    f = open(txt)
    n_bins = length // resolution + 1
    rg = max_range // resolution
    # mat = np.zeros((n_bins, rg))
    mat = np.zeros((n_bins, n_bins))
    cnt = 0
    for line in f:
        if cnt % 5000000 == 0:
            print('  Loading: ', cnt)
        cnt += 1
        p1, p2, v = line.strip().split()
        if v == 'NaN':
            continue
        p1, p2, v = int(p1), int(p2), float(v)
        if max(p1, p2) >= n_bins * resolution:
            continue
        if p1 > p2:
            p1, p2 = p2, p1
        p1, p2 = p1 // resolution, p2 // resolution
        # if p2 - p1 >= rg:
        #    continue
        # mat[p1, p2 - p1] += v
        mat[p1, p2] += v
    return mat


def save_temp_mat(folder, prefix, mat):
    current_idx = 0
    while os.path.exists(f'{folder}/{prefix}_{current_idx}.npy'):
        current_idx += 1
    np.save(f'{folder}/{prefix}_{current_idx}.npy', mat)


def enrichment_score2(mat, idx, line_width, distance_range=(20, 40), window_size=10):
    half = int(line_width // 2)
    x1, x2 = idx - half, idx - half + line_width
    if x1 == x2:
        x2 += 1
    #     print(f"x1,x2: {x1},{x2}")

    ########################################
    stripe_region = subsetNpMatrix(
        mat,
        (x1 - 2 * window_size, x2 + 2 * window_size),
        (distance_range[0], distance_range[1])
    )
    save_temp_mat('temp', 'original', stripe_region)
    ########################################

    new_mat = np.zeros((distance_range[1] - distance_range[0],))
    for j in range(distance_range[0], distance_range[1]):
        # if j < window_size + half or j >= mat.shape[1] - window_size - half:
        #     continue
        y = j - distance_range[0]
        _min_temp = subsetNpMatrix(mat, (x1, x2), (j - window_size - half, j + window_size + half + 1))
        if _min_temp == "Empty":
            continue
        line_min = np.median([_min_temp])
        _inner_neighbor = subsetNpMatrix(mat, (idx - half - window_size, x1),
                                         (j - window_size - half, j + window_size + half + 1))
        _outer_neighbor = subsetNpMatrix(mat, (x2 + 1, idx + half + window_size + 1),
                                         (j - window_size - half, j + window_size + half + 1))

        if _outer_neighbor == "Empty" or _inner_neighbor == "Empty":
            continue
        neighbor_mean = max(np.mean(_inner_neighbor), np.mean(_outer_neighbor))

        # There should be a lower bound for the expected value,
        # otherwise situations like (exp=0.01 and obs=0.02) would also be significant
        # Currently we can set this to 0 until KR norm factors can be loaded
        lower_b = 0  # This should be (1 / KR_norm_factors) if we refer to JuiceTools HICCUPS
        _exp = max(neighbor_mean, lower_b)
        _obs = int(line_min)  # the same as floor function when line_min > 0

        # _calculated_values: store all calculated exp-obs pairs in dictionary, in which keys are obs since
        #     they are always integers. Each _calculated_values[obs] is a binary tree for quick searching,
        #     and each tree leaf is a exp value corresponding to the obs value. Since exp values are float,
        #     there is also an integer index attached for searching the exp-obs in dictionary _poisson_stats
        #     (float cannot be dict keys).
        # _poisson_stats: record all calculated result in a dict. It should be
        #     _poisson_stats[(_exp, _obs)] = -log10(p). But _exp is a float and cannot be a dict key, we give
        #     each _exp a unique index and use the index.
        # stats_log: record all p value calculation. Just for benchmarking. Delete this when publishing.
        global _calculated_values, _poisson_stats, stats_log
        tolerance = 0.02

        # check if obs is a value calculated before
        if _obs in _calculated_values:
            # Find the nearest _exp values which were calculated before
            # One larger, one smaller
            (_upper, _lower) = _calculated_values[_obs].search(_exp)
            # If _upper is close enough to _exp, directly use the p value from (_upper-_obs) pair
            if _upper is not None and (_upper.key - _exp) < tolerance * _exp:
                _exp = _upper.key
                _exp_idx = _upper.val  # The integer index for _upper (float cannot be dict keys!)
                mlog_p_val = _poisson_stats[(_exp_idx, _obs)]
            else:
                # Else, calculate p value for _obs-_exp pair and store them in _calculated_values and _poisson_stats
                _exp_idx = _calculated_values[_obs].insert(_exp)  # insert to the binary tree and return an index
                Poiss = poisson(_exp)
                p_val = 1 - Poiss.cdf(_obs)
                if 0 < p_val < 1:
                    mlog_p_val = - np.log10(p_val)
                else:  # Some p values are too small, -log(0) will return an error, so we use -1 to temporarily replace
                    mlog_p_val = -1
                _poisson_stats[(_exp_idx, _obs)] = mlog_p_val
                stats_log.append([_exp, _obs, mlog_p_val])
        else:  # If _obs is not used before, generate a new binary tree _calculated_values[_obs]
            _calculated_values[_obs] = AVLTree()
            _exp_idx = _calculated_values[_obs].insert(_exp)
            # calculate p value for _obs-_exp pair and store them in _calculated_values and _poisson_stats
            Poiss = poisson(_exp)
            p_val = 1 - Poiss.cdf(_obs)
            if 0 < p_val < 1:
                mlog_p_val = - np.log10(p_val)
            else:  # Some p values are too small, -log(0) will return an error, so we use -1 to temporarily replace
                mlog_p_val = -1
            _poisson_stats[(_exp_idx, _obs)] = mlog_p_val
            stats_log.append([_exp, _obs, mlog_p_val])

        # Store enrichment score in new_mat
        new_mat[y] = mlog_p_val
    new_mat[new_mat < 0] = np.max(new_mat)  # Replace all "-1"s with the largest -log(p)

    ########################################
    save_temp_mat('temp', 'enrichment', new_mat)
    ########################################

    return new_mat


def find_max_slice(arr):
    _max, head, tail = 0, 0, 0
    _max_ending, h, t = 0, 0, 0
    i = 0
    while i < len(arr):
        _max_ending = _max_ending + arr[i]
        if _max_ending < 0:
            h, t = i + 1, i + 1
            _max_ending = 0
        else:
            t = i + 1
        if _max_ending > _max:
            head, tail, _max = h, t, _max_ending
        i += 1
    return head, tail, _max


def merge_positions(lst, merge_range):
    def _merge(small_lst):
        st = min([elm[0] for elm in small_lst])
        ed = max([elm[1] for elm in small_lst])
        head = min([elm[2] for elm in small_lst])
        tail = max([elm[3] for elm in small_lst])
        score = max([elm[4] for elm in small_lst])
        return [st, ed, head, tail, score]

    #
    new_lst = []
    temp = []
    for i, (idx, head, tail, score) in enumerate(lst):
        #         print(f"idx, head, tail, score: {idx}, {head}, {tail}, {score}")
        if i == 0:
            temp.append([idx, idx, head, tail, score])
        elif idx - temp[-1][1] <= merge_range:
            temp.append([idx, idx, head, tail, score])
        else:
            new_lst.append(_merge(temp))
            temp = [[idx, idx, head, tail, score]]
    new_lst.append(_merge(temp))
    #     print("==================")
    #     print(f"lst {lst}")
    #     print(f"new_lst {new_lst}")
    return new_lst


def phased_max_slice_arr(idx, arr_parallel):
    head, tail, _max = find_max_slice(arr_parallel)
    return (idx, head, tail, _max)


def _stripe_caller(mat, positions, max_range=150000, resolution=1000,
                   min_length=30000, closeness=50000,
                   stripe_width=1, merge=1, window_size=8, threshold=0.01,
                   N=False):
    def pack_tuple(*args):
        return (*args,)

    all_positions = []
    #
    # f = open(f'h_arr_chr1.txt', 'w')
    if N:  # parallel if #CPUs set
        lst = [idx for idx in list(sorted(positions.keys())) if
               not idx <= window_size or not idx >= mat.shape[0] - window_size]
        wtd = [positions[idx] for idx in list(sorted(positions.keys())) if
               not idx <= window_size or not idx >= mat.shape[0] - window_size]

        func = partial(enrichment_score2, mat, wtd, targeted_range, window_size)
        with Pool(N) as pool:
            arr = pool.map(func, lst)
        arr += np.log10(threshold)

        with Pool(N) as pool:
            all_positions = (pool.starmap(phased_max_slice_arr, zip(lst, arr)))
    #
    else:
        lst = [idx for idx in list(sorted(positions.keys())) if
               not idx <= window_size or not idx >= mat.shape[0] - window_size]
        wtd = [int(positions[idx]) for idx in list(sorted(positions.keys())) if
               not idx <= window_size or not idx >= mat.shape[0] - window_size]
        #         print(lst,wtd)
        for i, idx in enumerate(lst):
            if idx <= window_size or idx >= mat.shape[0] - window_size:
                continue
            # print(idx, lst[i], wtd[i])
            targeted_range = pack_tuple(0, max_range // resolution)
            arr = enrichment_score2(mat, idx, int(wtd[i]), \
                                    distance_range=targeted_range, \
                                    window_size=window_size)

            arr = arr + np.log10(threshold)
            head, tail, _max = find_max_slice(arr)
            all_positions.append((idx, head, tail, _max))
    #
    # Step 4: Merging
    print(' Merging...')
    print(f"pos to merge: {all_positions}")
    all_positions = merge_positions(all_positions, merge)
    #
    print(f"all_positions {all_positions}")
    print(' Filtering by distance and length ...')
    new_positions = []
    for elm in all_positions:
        # print(elm, end=' ')
        if (elm[3] - elm[2]) * resolution >= min_length and elm[2] * resolution <= closeness:
            # print(True)
            new_positions.append(elm)
        else:
            # print(False)
            pass
    print(len(new_positions))
    #
    # Step 5: Statistical test
    results = []
    print(' Statistical Tests...')
    for elm in new_positions:
        [st, ed, head, tail, score] = elm
        # p = stat_test(mat, st, ed, stripe_width, head, tail, window_size)
        # print(idx * resolution, p)
        # if score > threshold:
        results.append((st, (ed + 1), head, tail, score / (tail - head)))
    print(len(results))
    return results


def stripe_caller_all(
        hic_file,
        chromosomes,
        output_file,
        threshold=50., nstrata=50,
        max_range=150000, resolution=1000,
        min_length=30000, closeness=50000,
        stripe_width=1, merge=1, window_size=8,
        N=False
):
    ch_sizes = load_chrom_sizes('hg38')
    #
    f = open(output_file, 'w')
    f.write('#chr1\tx1\tx2\tchr2\ty1\ty2\tenrichment\n')
    #
    for ch in chromosomes:
        if ch == 'chr14':
            continue
        #
        print(f'Calling for {ch}...')
        hic2txt(hic_file, ch, resolution=resolution, output='temp.txt')
        #
        mat = txt2mat("temp.txt", length=ch_sizes[ch], max_range=max_range + min_length, resolution=resolution)
        mat = blank_diagonal2(mat, nstrata)
        #
        v_Peaks = {}
        h_Peaks = {}

        # tile over the chromosome...

        for ind in range(1800, mat.shape[1], 1800):
            upper = ind
            lower = ind - 1800
            mat_slice = mat[lower:upper, lower:upper]
            print(lower, upper)
            step = 600
            hM, hW, vM, vW = getPeakAndWidths(mat_slice, step)
            hM += lower
            vM += lower
            for i in range(len(hM)):
                if hM[i] not in h_Peaks.keys():
                    h_Peaks[hM[i]] = hW[i]
            for i in range(len(vM)):
                if vM[i] not in v_Peaks.keys():
                    v_Peaks[vM[i]] = vW[i]

        # horizontal
        mat = txt2horizontal('temp.txt', length=ch_sizes[ch], max_range=max_range + min_length, resolution=resolution)
        results = _stripe_caller(mat, h_Peaks, threshold=threshold,
                                 max_range=max_range, resolution=resolution,
                                 min_length=min_length, closeness=closeness,
                                 stripe_width=stripe_width, merge=merge, window_size=window_size,
                                 N=N)
        for (st, ed, hd, tl, sc) in results:
            f.write(f'{ch}\t{st * resolution}\t{ed * resolution}\t{ch}\t{max((st + hd), ed) * resolution}\t{(ed + tl) * resolution}\t{sc}\n')
        #         print(results)
        #
        # vertical
        mat = txt2vertical('temp.txt', length=ch_sizes[ch], max_range=max_range + min_length, resolution=resolution)
        results = _stripe_caller(mat, v_Peaks, threshold=threshold,
                                 max_range=max_range, resolution=resolution,
                                 min_length=min_length, closeness=closeness,
                                 stripe_width=stripe_width, merge=merge, window_size=window_size,
                                 N=N)
        for (st, ed, hd, tl, sc) in results:
            f.write(f'{ch}\t{(st - tl) * resolution}\t{min((ed - hd), st) * resolution}\t{ch}\t{st * resolution}\t{ed * resolution}\t{sc}\n')
    #
    f.close()


def visualize_stats_log(stats_log, name):
    plt.figure(figsize=(12, 12))
    stats_log = np.array(stats_log)
    plt.scatter(stats_log[:, 0], stats_log[:, 1], c=stats_log[:, 1], s=1)
    plt.xlabel('Expected')
    plt.ylabel('Observed')
    plt.colorbar()
    plt.title(f'{len(stats_log)} Poisson Tests')
    plt.savefig(name)
    plt.close()


if __name__ == '__main__':
    import time
    import argparse

    # chromosomes = [f'chr{i}' for i in list(range(1, 23)) + ['X']]
    chromosomes = ['chr1']

    # hic_file = '/nfs/turbo/umms-drjieliu/proj/4dn/data/microC/HFF/raw/HFFc6.hic'
    # thr = 0.01

    parser = argparse.ArgumentParser(description='stripecaller CPU arguements')
    parser.add_argument("--N", help='CPU_cores', dest='N', type=int, default=0)
    args = parser.parse_args()
    print(args.N)

    # start_time = time.time()
    # stripe_caller_all(
    #    hic_file=hic_file,
    #    chromosomes=chromosomes,
    #    output_file='HFF_MicroC_stripes_chr1.bedpe',
    #    threshold=thr,
    #    N=args.N
    # )
    # print("microC/HFF/raw/HFFc6.hic took:\n--- %s seconds ---" % (time.time() - start_time))
    # original: 843 seconds
    # pooled: 509.35 seconds --nodes=1 --ntasks=1 --cpus-per-task=16 --mem-per-cpu=8GB
    # visualize_stats_log(stats_log, 'HFF_MicroC_chr1_stats_log.png')

    # #     start_time = time.time()
    # hic_file = '/nfs/turbo/umms-drjieliu/proj/4dn/data/microC/hESC/raw/H1-hESC.hic'
    # thr = 0.01
    # stripe_caller_all(
    #     hic_file=hic_file,
    #     chromosomes=chromosomes,
    #     output_file='H1_MicroC_stripes_chr1.bedpe',
    #     threshold=thr
    # )
    # #     print("microC/hESC/raw/H1-hESC.hic took:\n--- %s seconds ---" % (time.time() - start_time))

    start_time = time.time()
    hic_file = '/nfs/turbo/umms-drjieliu/proj/4dn/data/bulkHiC/GM12878/GM12878.hic'
    thr = 0.01
    #     stripe_caller_all(
    #         hic_file=hic_file,
    #         chromosomes=chromosomes,
    #         output_file='GM12878_HiC_stripes_chr1.bedpe',
    #         threshold=thr, nstrata=50,
    #         max_range=5000000, resolution=25000,
    #         min_length=1000000, closeness=1000000,
    #         stripe_width=1, merge=1, window_size=8,
    #         N=args.N
    #     )

    stripe_caller_all(
        hic_file=hic_file,
        chromosomes=chromosomes,
        output_file='GM12878_HiC_stripes_chr1.bedpe',
        threshold=thr, nstrata=50,
        max_range=17500000, resolution=25000,
        min_length=1000000, closeness=1000000,
        stripe_width=1, merge=1, window_size=8,
        N=args.N
    )
    print("bulkHiC/GM12878/GM12878.hic took:\n--- %s seconds ---" % (time.time() - start_time))
