# Detecting Bursts and Communities in Research Streams

Authors: Priya Nair and Asha Raman
Contact: research-stream@synapse-demo.example.org
Published: 2026
Note: sample document written for the Synapse demo corpus; the references are real.

Abstract
Research fields do not grow smoothly: a new idea appears, attention bursts, and the community either absorbs it
or splits into new lines of work. We combine burst detection on yearly term frequencies with community detection
on citation graphs to describe how topics merge and split over decades, and discuss what the structure of
citation networks implies for such analyses.

Keywords: burst detection, community detection, citation networks, temporal analysis

## 1 Bursts

Kleinberg models a stream with a two-state automaton: a base state that emits a word at its usual rate and a burst
state that emits it more often, with a cost for entering the burst state [1]. The cheapest state sequence, found by
dynamic programming, marks the bursts, and their weights rank how surprising they are (Kleinberg, 2003).

## 2 Communities and network structure

Citation graphs are not random. Small-world networks combine high clustering with short paths [2], and degree
distributions follow heavy tails because well-cited papers attract further citations [3]. Communities can be
found by removing high-betweenness edges [4] or, at scale, by greedy modularity optimisation such as the Louvain
method [5]. A broad survey of these structural results is given by Newman [6].

## 3 Topic evolution

Clustering each era separately and linking clusters across consecutive eras turns a static map into a temporal
graph in which merges and splits become visible [1, 5]. Bursty terms [1] often mark the moment a split happens.

References
1. J. Kleinberg. Bursty and hierarchical structure in streams. Data Mining and Knowledge Discovery, 7(4):373-397, 2003.
2. D. J. Watts and S. H. Strogatz. Collective dynamics of 'small-world' networks. Nature, 393:440-442, 1998.
3. A.-L. Barabási and R. Albert. Emergence of scaling in random networks. Science, 286(5439):509-512, 1999.
4. M. Girvan and M. E. J. Newman. Community structure in social and biological networks. PNAS, 99(12):7821-7826, 2002.
5. V. D. Blondel, J.-L. Guillaume, R. Lambiotte, and E. Lefebvre. Fast unfolding of communities in large networks. Journal of Statistical Mechanics, P10008, 2008.
6. M. E. J. Newman. The structure and function of complex networks. SIAM Review, 45(2):167-256, 2003.
