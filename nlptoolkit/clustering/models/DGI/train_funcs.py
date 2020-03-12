# -*- coding: utf-8 -*-
"""
Created on Wed Jul 31 10:44:05 2019

@author: WT
"""
import os
import networkx as nx
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from .preprocessing_funcs import load_pickle, save_as_pickle, generate_text_graph
import logging

logging.basicConfig(format='%(asctime)s [%(levelname)s]: %(message)s', \
                    datefmt='%m/%d/%Y %I:%M:%S %p', level=logging.INFO)
logger = logging.getLogger(__file__)

def get_X_A_hat(G, corrupt=False):
    A = nx.to_numpy_matrix(G, weight="weight")
    A = A + np.eye(G.number_of_nodes())
    X = np.eye(G.number_of_nodes()) # Features are just identity matrix
    
    if corrupt:
        np.random.shuffle(X)
    
    degrees = []
    for d in G.degree(weight=None):
        if d == 0:
            degrees.append(0)
        else:
            degrees.append(d[1]**(-0.5))
    degrees = np.diag(degrees)
    A_hat = degrees@A@degrees
    
    X = torch.from_numpy(X).float()
    A_hat = torch.tensor(A_hat).float()
    return X, A_hat

class JSdiv_Loss(nn.Module):
    def __init__(self):
        super(JSdiv_Loss, self).__init__()
        self.BCE_pos = nn.BCELoss(reduction='mean')
        self.BCE_neg = nn.BCELoss(reduction='mean')
    
    def forward(self, D_pos, D_neg):
        label_pos = torch.ones(D_pos.shape[0])
        label_neg = torch.zeros(D_neg.shape[0])
        
        if D_pos.is_cuda:
            label_pos, label_neg = label_pos.cuda(), label_neg.cuda()
            
        pos_loss = self.BCE_pos(D_pos, label_pos)
        neg_loss = self.BCE_neg(D_neg, label_neg)
        total_loss = 0.5*(pos_loss + neg_loss)
        return total_loss

def load_datasets(args):
    """Loads dataset and graph if exists, else create and process them from raw data
    Returns --->
    f: torch tensor input of GCN (Identity matrix)
    X: input of GCN (Identity matrix)
    A_hat: transformed adjacency matrix A
    selected: indexes of selected labelled nodes for training
    test_idxs: indexes of not-selected nodes for inference/testing
    labels_selected: labels of selected labelled nodes for training
    labels_not_selected: labels of not-selected labelled nodes for inference/testing
    """
    logger.info("Loading data...")
    df_data_path = "./data/df_data.pkl"
    graph_path = "./data/text_graph.pkl"
    if not os.path.isfile(df_data_path) or not os.path.isfile(graph_path):
        logger.info("Building datasets and graph from raw data... Note this will take quite a while...")
        generate_text_graph(args.train_data, args.max_vocab_len)
    
    G_dict = load_pickle("text_graph.pkl")
    G = G_dict["graph"]
    del G_dict

    return G
    
def load_state(net, optimizer, scheduler, model_no=0, load_best=False):
    """ Loads saved model and optimizer states if exists """
    logger.info("Initializing model and optimizer states...")
    base_path = "./data/"
    checkpoint_path = os.path.join(base_path,"test_checkpoint_%d.pth.tar" % model_no)
    best_path = os.path.join(base_path,"test_model_best_%d.pth.tar" % model_no)
    start_epoch, best_pred, checkpoint = 0, 0, None
    if (load_best == True) and os.path.isfile(best_path):
        checkpoint = torch.load(best_path)
        logger.info("Loaded best model.")
    elif os.path.isfile(checkpoint_path):
        checkpoint = torch.load(checkpoint_path)
        logger.info("Loaded checkpoint model.")
    if checkpoint != None:
        start_epoch = checkpoint['epoch']
        best_pred = checkpoint['best_acc']
        net.load_state_dict(checkpoint['state_dict'])
        optimizer.load_state_dict(checkpoint['optimizer'])
        scheduler.load_state_dict(checkpoint['scheduler'])
        logger.info("Loaded model and optimizer.")    
    return start_epoch, best_pred

def load_results(model_no=0):
    """ Loads saved results if exists """
    losses_path = "./data/train_losses_per_epoch_%d.pkl" % model_no
    if os.path.isfile(losses_path):
        losses_per_epoch = load_pickle("train_losses_per_epoch_%d.pkl" % model_no)
        logger.info("Loaded results buffer")
    else:
        losses_per_epoch = []
    return losses_per_epoch

def evaluate(output, labels_e):
    if len(labels_e) == 0:
        return 0
    else:
        _, labels = output.max(1); labels = labels.cpu().numpy() if labels.is_cuda else labels.numpy()
        return sum([(e) for e in labels_e] == labels)/len(labels)

def infer(f, test_idxs, net):
    logger.info("Evaluating on inference data...")
    net.eval()
    with torch.no_grad():
        pred_labels = net(f)
    if pred_labels.is_cuda:
        pred_labels = list(pred_labels[test_idxs].max(1)[1].cpu().numpy())
    else:
        pred_labels = list(pred_labels[test_idxs].max(1)[1].numpy())
    pred_labels = [i for i in pred_labels]
    test_idxs = [i - test_idxs[0] for i in test_idxs]
    df_results = pd.DataFrame(columns=["index", "predicted_label"])
    df_results.loc[:, "index"] = test_idxs
    df_results.loc[:, "predicted_label"] = pred_labels
    df_results.to_csv("./data/results.csv", columns=df_results.columns, index=False)
    logger.info("Done and saved!")
    return df_results