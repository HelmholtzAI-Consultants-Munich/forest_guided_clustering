import numpy as np
import pandas as pd

import seaborn as sns
import matplotlib.pyplot as plt

from scipy.stats import f_oneway

from sklearn_extra.cluster import KMedoids
from sklearn.preprocessing import StandardScaler
from sklearn.preprocessing import MinMaxScaler

from tqdm import tqdm

def forest_guided_clustering(model, data, target_column, output, max_K = 6, thr_pvalue = 0.05,
                             random_state=42, 
                             bootstraps = 300, 
                             max_iter_clustering = 300, 
                             number_of_clusters = None):
    # check if random forest is regressor or classifier
    is_regressor = 'RandomForestRegressor' in str(type(model))
    is_classifier = 'RandomForestClassifier' in str(type(model))
    if is_regressor is True:
        method = "regression"
        print("Interpreting RandomForestRegressor")
    elif is_classifier is True:
        method = "clustering"
        print("Interpreting RandomForestClassifier")
    else:
        raise ValueError(f'Do not recognize {str(type(model))}. Can only work with sklearn RandomForestRegressor or RandomForestClassifier.')
    
    
    y = data.loc[:,target_column].to_numpy()
    X = data.drop(columns=[target_column]).to_numpy()
    
    distanceMatrix = 1 - proximityMatrix(model, X)
    if number_of_clusters is None:
        k = optimizeK(distanceMatrix, X, y, max_K = 6,
                      random_state=random_state, 
                      bootstraps = bootstraps,
                      max_iter_clustering = max_iter_clustering,
                      method = method)
    else:
        k = number_of_clusters
    
    plot_forest_guided_clustering(model, data, target_column, k, output, thr_pvalue = thr_pvalue, random_state = random_state)
    
    return k

def optimizeK(distance_matrix, x, y,
              max_K = 6, 
              random_state=42, 
              discart_value = 0.6,
              bootstraps = 300, 
              max_iter_clustering = 300,
              method = "clustering"):
    
    score_min = np.inf
    optimal_k = 1
    
    for k in tqdm(range(2, max_K)):
        #compute clusters        
        cluster_method = lambda X: KMedoids(n_clusters=k, 
                                            random_state=random_state, init = 'build',
                                            method = "pam", max_iter=max_iter_clustering).fit(X).labels_
        labels = cluster_method(distance_matrix)

        # compute jaccard indices
        index_per_cluster = compute_stability_indices(distance_matrix, 
                                                      cluster_method = cluster_method, 
                                                      seed = random_state, 
                                                      bootstraps = bootstraps)
        min_index = min([index_per_cluster[cluster] for cluster in index_per_cluster.keys()])
        
        # only continue if jaccard indices are all larger 0.6 (thus all clusters are stable)
        print('For number of cluster {} the Jaccard Index is {}'.format(k, min_index))
        if min_index > discart_value:
            if method == "clustering":
                # compute balanced purities
                score = compute_balanced_average_purity(y, labels)
            elif method == "regression":
                # compute the total within cluster variation
                score = compute_total_within_cluster_variation(y, labels)
            if score<score_min:
                optimal_k = k
                score_min = score
            print('For number of cluster {} the score is {}'.format(k,score))
        else:
            print('Clustering is instable, no score computed!')
    return optimal_k

def compute_total_within_cluster_variation(y, labels):
    score = 0
    for cluster in np.unique(labels):
        y_cluster = y[labels == cluster]
        score += np.var(y_cluster)*len(y_cluster)
        
    return score
        
def compute_balanced_average_purity(y, labels):
    n0 = sum(y==0)
    n1 = sum(y==1)
    
    if n0<=n1:
        small_label = 0
        large_label = 1
        up_scaling_factor = n1/n0
    else:
        small_label = 1
        large_label = 0
        up_scaling_factor = n0/n1
    balanced_purities = []
    for cluster in np.unique(labels):
        y_cluster = y[labels == cluster]
        
        x_small = sum(y_cluster == small_label)*up_scaling_factor
        x_large = sum(y_cluster == large_label)
        x_tot = x_small+x_large
        balanced_purity = (x_small/x_tot)*(x_large/x_tot)
        normalized_balanced_purity = balanced_purity/0.25
        
        balanced_purities.append(normalized_balanced_purity)
    
    average_balanced_purities = np.mean(balanced_purities)
    return average_balanced_purities


def compute_stability_indices(distance_matrix, cluster_method, bootstraps = 300, seed = 42):
    matrix_shape = distance_matrix.shape
    assert len(matrix_shape) == 2, "error distance_matrix is not a matrix"
    assert matrix_shape[0] == matrix_shape[1], "error distance matrix is not square"
    np.random.seed = seed
    
    labels = cluster_method(distance_matrix)
    clusters = np.unique(labels)
    number_datapoints = len(labels)
    index_vector = np.arange(number_datapoints)
    
    indices_original_clusters = _translate_cluster_labels_to_dictionary_of_index_sets_per_cluster(labels)
    
    index_per_cluster = {cluster: 0 for cluster in clusters}
    
    for i in range(bootstraps):
        bootsrapped_distance_matrix, mapping_bootstrapped_indices_to_original_indices = bootstrap_matrix(distance_matrix)
        bootstrapped_labels = cluster_method(bootsrapped_distance_matrix)
        # now compute the indices for the different clusters
        indices_bootstrap_clusters = _translate_cluster_labels_to_dictionary_of_index_sets_per_cluster(bootstrapped_labels, 
                                                                                                       mapping = mapping_bootstrapped_indices_to_original_indices)
        
        
        jaccard_matrix = _compute_jaccard_matrix(clusters, indices_bootstrap_clusters, indices_original_clusters)
        
        # compute optimal jaccard index for each cluster -> choose maximum possible jaccard index first
        for cluster_round in range(len(jaccard_matrix)):
            best_index = jaccard_matrix.max(axis=1).max()       
            original_cluster_number = jaccard_matrix.max(axis=1).argmax()
            bootstrapped_cluster_number = jaccard_matrix[original_cluster_number].argmax()
            jaccard_matrix[original_cluster_number] = -np.inf
            jaccard_matrix[:,bootstrapped_cluster_number] = -np.inf

            original_cluster = clusters[original_cluster_number]
            index_per_cluster[original_cluster] += best_index
                                    
    # normalize
    index_per_cluster = {cluster: index_per_cluster[cluster]/bootstraps for cluster in clusters}
        
    return index_per_cluster

def bootstrap_matrix(M):
    lm = len(M)
    bootstrapped_samples = np.random.choice(np.arange(lm), lm)
    M_bootstrapped = M[:,bootstrapped_samples][bootstrapped_samples,:]
    
    mapping_bootstrapped_indices_to_original_indices = {bootstrapped : original for bootstrapped, original in enumerate(bootstrapped_samples)}
    
    return M_bootstrapped, mapping_bootstrapped_indices_to_original_indices

def proximityMatrix(model, X, normalize=True):  
    '''computes the proximity matrix from the model'''

    terminals = model.apply(X)
    nTrees = terminals.shape[1]

    a = 0
    proxMat = 0

    for i in range(nTrees):
        a = terminals[:,i]
        proxMat += np.equal.outer(a, a)

    if normalize:
        proxMat = proxMat / nTrees

    return proxMat 


def _translate_cluster_labels_to_dictionary_of_index_sets_per_cluster(labels, mapping = False):

    clusters = np.unique(labels)
    number_datapoints = len(labels)
    index_vector = np.arange(number_datapoints)
    
    indices_clusters = {}
    for cluster in clusters:
        indices = set(index_vector[labels == cluster])
        if mapping is not False:
            #translate from the bootstrapped indices to the original naming of the indices
            indices = [mapping[index] for index in indices]
        
        indices_clusters[cluster] = indices
        

        
    return indices_clusters

def _compute_jaccard_matrix(clusters, indices_bootstrap_clusters, indices_original_clusters):
        
    jaccard_matrix = np.zeros([len(clusters), len(clusters)])
    for i, cluster_original in enumerate(clusters):
        for j, cluster_bootstrap in enumerate(clusters):
            indices_bootstrap = indices_bootstrap_clusters[cluster_bootstrap]
            indices_original = indices_original_clusters[cluster_original]

            intersection = indices_original.intersection(indices_bootstrap)
            union = indices_original.union(indices_bootstrap)

            jaccard_matrix[i,j] = len(intersection)/len(union)
            
    return jaccard_matrix


def _scale_standard(X):
        
    SCALE = StandardScaler()
    SCALE.fit(X)

    X_scale = pd.DataFrame(SCALE.transform(X))
    X_scale.columns = X.columns
    X_scale.reset_index(inplace=True,drop=True)

    return X_scale


def _scale_minmax(X):
        
    SCALE = MinMaxScaler()
    SCALE.fit(X)

    X_scale = pd.DataFrame(SCALE.transform(X))
    X_scale.columns = X.columns
    X_scale.reset_index(inplace=True,drop=True)

    return X_scale

def plot_forest_guided_clustering(model, data, target_column, k, output, thr_pvalue, random_state):
    X = data.loc[:, data.columns != 'target']
    features = X.columns

    proximity_matrix = proximityMatrix(model, X)
    kmedoids = KMedoids(n_clusters=k, random_state=random_state).fit(proximity_matrix)
    X['cluster'] = kmedoids.labels_
    
    X_heatmap = X.copy()
    X_heatmap['target'] = data.target
    X_heatmap.loc['p_value'] = None

    for feature in features:
        df = X[[feature,'cluster']]
        df.columns = ['feature', 'cluster']
        
        
        # anova test
        list_of_df = [df.feature[df.cluster == cluster] for cluster in set(df.cluster)]
        anova = f_oneway(*list_of_df)
        X_heatmap.loc['p_value',feature] = anova.pvalue

    X_heatmap.loc['p_value','cluster'] = 0  
    X_heatmap.loc['p_value','target'] = -1  
    X_heatmap = X_heatmap.transpose()
    X_heatmap = X_heatmap.loc[X_heatmap.p_value < thr_pvalue]
    X_heatmap.sort_values(by='p_value', inplace=True)
    X_heatmap.drop('p_value', axis=1, inplace=True)
    X_heatmap.sort_values(by='cluster', axis=1, inplace=True)
    X_heatmap = _scale_minmax(X_heatmap.transpose())

    X_heatmap_final = pd.DataFrame(columns = X_heatmap.columns)
    clusters = X_heatmap.cluster.unique()
    for cluster in clusters:
        #print(X_heatmap[X_heatmap.cluster == cluster])
        X_heatmap_final = X_heatmap_final.append(X_heatmap[X_heatmap.cluster == cluster], ignore_index=True)
        X_heatmap_final = X_heatmap_final.append(pd.DataFrame(np.nan, index = np.arange(5), columns = X_heatmap.columns), ignore_index=True)
    X_heatmap_final = X_heatmap_final[:-5]
    X_heatmap_final
    
    plot = sns.heatmap(X_heatmap_final.transpose(), xticklabels=False, yticklabels = 1, cmap='coolwarm', cbar_kws={'label': 'standardized feature values'})
    plot.set(title='Forest-guided clustering')
    plot.set_yticklabels(X_heatmap_final.columns, size = 6)
    plt.savefig(output, bbox_inches='tight', dpi = 300)