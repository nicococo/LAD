import cvxopt as co
import numpy as np
import sklearn.metrics as metric
import scipy.io as io

from kernel import Kernel
from ocsvm import OCSVM
from latent_ocsvm import LatentOCSVM

from toydata import ToyData
from so_hmm import SOHMM


def get_model(num_exm, num_train, lens, block_len, blocks=1, anomaly_prob=0.15):
    print('Generating {0} sequences, {1} for training, each with {2} anomaly probability.'.format(num_exm, num_train,
                                                                                                  anomaly_prob))
    cnt = 0
    X = []
    Y = []
    label = []
    lblcnt = co.matrix(0.0, (1, lens))
    for i in range(num_exm):
        (exm, lbl, marker) = ToyData.get_2state_anom_seq(lens, block_len, anom_prob=anomaly_prob, num_blocks=blocks)
        cnt += lens
        X.append(exm)
        Y.append(lbl)
        label.append(marker)
        # some lbl statistics
        if i < num_train:
            lblcnt += lbl
    X = normalize_sequence_data(X, num_train)
    return SOHMM(X[0:num_train], Y[0:num_train]), SOHMM(X[num_train:], Y[num_train:]), SOHMM(X, Y), label


def normalize_sequence_data(X, num_train, dims=1):
    cnt = 0
    tst_mean = co.matrix(0.0, (1, dims))
    for i in range(num_train):
        lens = len(X[i][0, :])
        cnt += lens
        tst_mean += co.matrix(1.0, (1, lens)) * X[i].trans()
    tst_mean /= float(cnt)
    print tst_mean

    max_val = co.matrix(-1e10, (1, dims))
    for i in range(len(X)):
        for d in range(dims):
            X[i][d, :] = X[i][d, :] - tst_mean[d]
            foo = np.max(np.abs(X[i][d, :]))
            if i < num_train:
                max_val[d] = np.max([max_val[d], foo])

    print max_val
    for i in range(len(X)):
        for d in range(dims):
            X[i][d, :] /= max_val[d]

    cnt = 0
    max_val = co.matrix(-1e10, (1, dims))
    tst_mean = co.matrix(0.0, (1, dims))
    for i in range(len(X)):
        lens = len(X[i][0, :])
        cnt += lens
        tst_mean += co.matrix(1.0, (1, lens)) * X[i].trans()
        for d in range(dims):
            foo = np.max(np.abs(X[i][d, :]))
            max_val[d] = np.max([max_val[d], foo])
    print tst_mean / float(cnt)
    print max_val
    return X


def build_seq_kernel(data, ord=2, type='linear', param=1.0):
    # all sequences have the same length
    N = len(data)
    (F, LEN) = data[0].size
    phi = co.matrix(0.0, (F * LEN, N))
    for i in xrange(N):
        for f in xrange(F):
            phi[(f * LEN):(f * LEN) + LEN, i] = data[i][f, :].trans()
        if ord >= 1:
            phi[:, i] /= np.linalg.norm(phi[:, i], ord=ord)
    kern = Kernel.get_kernel(phi, phi, type=type, param=param)
    return kern, phi


def build_kernel(data, labels, num_train, bins=2, ord=2, typ='linear', param=1.0):
    return build_seq_kernel(data, ord=ord, type=typ.lower(), param=param)


def test_bayes(phi, kern, train, test, num_train, anom_prob, labels):
    # bayes classifier
    (DIMS, N) = phi.size
    w_bayes = co.matrix(-1.0, (DIMS, 1))
    pred = w_bayes.trans() * phi[:, num_train:]
    (fpr, tpr, thres) = metric.roc_curve(labels[num_train:], pred.trans())
    auc = metric.auc(fpr, tpr)
    return auc


def test_hmad(phi, kern, train, test, num_train, anom_prob, labels, zero_shot=False, param=2):
    auc = 0.5

    ntrain = SOHMM(train.X, train.y, num_states=param)
    ntest = SOHMM(test.X, test.y, num_states=param)

    # train structured anomaly detection
    sad = LatentOCSVM(train, C=1.0 / (num_train * anom_prob))
    (lsol, lats, thres) = sad.train_dc(max_iter=60, zero_shot=zero_shot)
    (pred_vals, pred_lats) = sad.apply(test)
    (fpr, tpr, thres) = metric.roc_curve(labels[num_train:], pred_vals)
    auc = metric.auc(fpr, tpr)
    return auc


if __name__ == '__main__':
    LENS = 600
    EXMS = 800
    EXMS_TRAIN = 400
    ANOM_PROB = 0.05
    REPS = 50
    BLOCK_LEN = 120

    BLOCKS = [2, 3, 4, 6, 8, 12]

    methods = ['HMAD']
    kernels = ['']
    kparams = ['']
    ords    = [1]

    # collected means
    res = []
    for r in xrange(REPS):
        for b in xrange(len(BLOCKS)):
            (train, test, comb, labels) = get_model(EXMS, EXMS_TRAIN, LENS, BLOCK_LEN, blocks=2,
                                                    anomaly_prob=ANOM_PROB)
            for m in range(len(methods)):
                name = 'test_{0}'.format(methods[m].lower())
                (kern, phi) = build_kernel(comb.X, comb.y, EXMS_TRAIN, ord=ords[m], typ=kernels[m].lower(),
                                           param=kparams[m])
                print('Calling {0}'.format(name))
                auc = eval(name)(phi, kern, train, test, EXMS_TRAIN, ANOM_PROB, labels, param=BLOCKS[b])
                print('-------------------------------------------------------------------------------')
                print
                print('Iter {0}/{1} in block {2}/{3} for method {4} ({5}/{6}) got AUC = {7}.'.format(r + 1, REPS, b + 1,
                                                                                                     len(BLOCKS), name,
                                                                                                     m + 1,
                                                                                                     len(methods), auc))
                print
                print('-------------------------------------------------------------------------------')

                if len(res) <= b:
                    res.append([])
                mlist = res[b]
                if len(mlist) <= m:
                    mlist.append([])
                cur = mlist[m]
                cur.append(auc)

    print('RESULTS >-----------------------------------------')
    print
    aucs = np.ones((len(methods), len(BLOCKS)))
    stds = np.ones((len(methods), len(BLOCKS)))
    varis = np.ones((len(methods), len(BLOCKS)))
    names = []

    for b in range(len(BLOCKS)):
        print("BLOCKS={0}:".format(BLOCKS[b]))
        for m in range(len(methods)):
            auc = np.mean(res[b][m])
            std = np.std(res[b][m])
            var = np.var(res[b][m])
            aucs[m, b] = auc
            stds[m, b] = std
            varis[m, b] = var
            kname = ''
            if kernels[m] == 'RBF' or kernels[m] == 'Hist':
                kname = ' ({0} {1})'.format(kernels[m], kparams[m])
            elif kernels[m] == 'Linear':
                kname = ' ({0})'.format(kernels[m])
            name = '{0}{1} [{2}]'.format(methods[m], kname, ords[m])
            if len(names) <= m:
                names.append(name)
            print("   m={0}: AUC={1} STD={2} VAR={3}".format(name, auc, std, var))
        print

    print aucs
    # store result as a file
    data = {'LENS': LENS, 'EXMS': EXMS, 'EXMS_TRAIN': EXMS_TRAIN, 'ANOM_PROB': ANOM_PROB, 'REPS': REPS,
            'BLOCKS': BLOCKS, 'methods': methods, 'kernels': kernels, 'kparams': kparams, 'ords': ords, 'res': res,
            'aucs': aucs, 'stds': stds, 'varis': varis, 'names': names}

    io.savemat('15_icml_toy_states_c0.mat', data)

    print('finished')
