"""Abstract class for graph embedding models."""
from typing import Union, Dict, List
from ensmallen_graph import EnsmallenGraph
import pandas as pd
import numpy as np
from tensorflow.keras.optimizers import Optimizer
from tensorflow.keras.callbacks import EarlyStopping
from .word2vec import Word2Vec
from ..sequences import Node2VecSequence


class Node2Vec:
    """Abstract class for sequence embedding models."""

    def __init__(
        self,
        graph: EnsmallenGraph,
        word2vec_model: Word2Vec,
        embedding_size: int = 100,
        optimizer: Union[str, Optimizer] = None,
        negative_samples: int = 10,
        walk_length: int = 128,
        batch_size: int = 256,
        iterations: int = 1,
        window_size: int = 7,
        return_weight: float = 1.0,
        explore_weight: float = 1.0,
        change_node_type_weight: float = 1.0,
        change_edge_type_weight: float = 1.0,
        max_neighbours: int = None,
        elapsed_epochs: int = 0,
        support_mirror_strategy: bool = False,
        random_state: int = 42,
        dense_node_mapping: Dict[int, int] = None
    ):
        """Create new sequence Embedder model.

        Parameters
        -------------------------------------------
        graph: EnsmallenGraph,
            Graph to be embedded.
        word2vec_model: Word2Vec,
            Word2Vec model to use.
        embedding_size: int = 100,
            Dimension of the embedding.
        optimizer: Union[str, Optimizer] = None,
            The optimizer to be used during the training of the model.
            By default, if None is provided, Nadam with learning rate
            set at 0.01 is used.
        window_size: int = 7,
            Window size for the local context.
            On the borders the window size is trimmed.
        negative_samples: int = 10,
            The number of negative classes to randomly sample per batch.
            This single sample of negative classes is evaluated for each element in the batch.
        walk_length: int = 128,
            Maximal length of the walks.
        batch_size: int = 256,
            Number of nodes to include in a single batch.
        iterations: int = 1,
            Number of iterations of the single walks.
        window_size: int = 7,
            Window size for the local context.
            On the borders the window size is trimmed.
        shuffle: bool = True,
            Whether to shuffle the vectors.
        return_weight: float = 1.0,
            Weight on the probability of returning to the same node the walk just came from
            Having this higher tends the walks to be
            more like a Breadth-First Search.
            Having this very high  (> 2) makes search very local.
            Equal to the inverse of p in the Node2Vec paper.
        explore_weight: float = 1.0,
            Weight on the probability of visiting a neighbor node
            to the one we're coming from in the random walk
            Having this higher tends the walks to be
            more like a Depth-First Search.
            Having this very high makes search more outward.
            Having this very low makes search very local.
            Equal to the inverse of q in the Node2Vec paper.
        change_node_type_weight: float = 1.0,
            Weight on the probability of visiting a neighbor node of a
            different type than the previous node. This only applies to
            colored graphs, otherwise it has no impact.
        change_edge_type_weight: float = 1.0,
            Weight on the probability of visiting a neighbor edge of a
            different type than the previous edge. This only applies to
            multigraphs, otherwise it has no impact.
        max_neighbours: int = None,
            Number of maximum neighbours to consider when using approximated walks.
            By default, None, we execute exact random walks.
            This is mainly useful for graphs containing nodes with extremely high degrees.
        elapsed_epochs: int = 0,
            Number of elapsed epochs to init state of generator.
        support_mirror_strategy: bool = False,
            Wethever to patch support for mirror strategy.
            At the time of writing, TensorFlow's MirrorStrategy does not support
            input values different from floats, therefore to support it we need
            to convert the unsigned int 32 values that represent the indices of
            the embedding layers we receive from Ensmallen to floats.
            This will generally slow down performance, but in the context of
            exploiting multiple GPUs it may be unnoticeable.
        random_state: int = 42,
            The random state to reproduce the training sequence.
        dense_node_mapping: Dict[int, int] = None,
            Mapping to use for converting sparse walk space into a dense space.
            This object can be created using the method (available from the
            graph object created using EnsmallenGraph)
            called `get_dense_node_mapping` that returns a mapping from
            the non trap nodes (those from where a walk could start) and
            maps these nodes into a dense range of values.
        """
        self._sequence = Node2VecSequence(
            graph,
            walk_length=walk_length,
            batch_size=batch_size,
            iterations=iterations,
            window_size=window_size,
            return_weight=return_weight,
            explore_weight=explore_weight,
            change_node_type_weight=change_node_type_weight,
            change_edge_type_weight=change_edge_type_weight,
            max_neighbours=max_neighbours,
            support_mirror_strategy=support_mirror_strategy,
            elapsed_epochs=elapsed_epochs,
            random_state=random_state,
            dense_node_mapping=dense_node_mapping
        )
        self._model = word2vec_model(
            vocabulary_size=graph.get_nodes_number(),
            embedding_size=embedding_size,
            model_name="Graph{}".format(word2vec_model.__name__),
            optimizer=optimizer,
            window_size=window_size,
            negative_samples=negative_samples
        )

    def fit(
        self,
        epochs: int = 100,
        monitor: str = "loss",
        min_delta: float = 0.1,
        patience: int = 5,
        mode: str = "min",
        **kwargs: Dict
    ) -> pd.DataFrame:
        """Return pandas dataframe with training history.

        Parameters
        -----------------------
        epochs: int = 100,
            Epochs to train the model for.
        monitor: str = "loss",
            Metric to monitor for early stopping.
        min_delta: float = 0.1,
            Minimum delta of metric to stop the training.
        patience: int = 5,
            Number of epochs to wait for when the given minimum delta is not
            achieved.
        mode: str = "min",
            Direction of the variation of the monitored metric.
        **kwargs: Dict,
            Additional kwargs to pass to the Keras fit call.

        Returns
        -----------------------
        Dataframe with training history.
        """
        return self._model.fit(
            self._sequence,
            steps_per_epoch=self._sequence.steps_per_epoch,
            epochs=epochs,
            callbacks=[
                EarlyStopping(
                    monitor=monitor,
                    min_delta=min_delta,
                    patience=patience,
                    mode=mode,
                    restore_best_weights=True
                ),
                *kwargs.get("callbacks", ())
            ],
            **kwargs
        )

    def summary(self):
        """Print model summary."""
        self._model.summary()

    @property
    def embedding(self) -> np.ndarray:
        """Return model embeddings."""
        return self._model.embedding

    def get_embedding_dataframe(self, term_names: List[str]) -> pd.DataFrame:
        """Return terms embedding using given index names.

        Parameters
        -----------------------------
        term_names: List[str],
            List of terms to be used as index names.
        """
        return self._model.get_embedding_dataframe(term_names)

    def save_embedding(self, path: str, term_names: List[str]):
        """Save terms embedding using given index names.

        Parameters
        -----------------------------
        path: str,
            Save embedding as csv to given path.
        term_names: List[str],
            List of terms to be used as index names.
        """
        self._model.save_embedding(path, term_names)

    @property
    def name(self) -> str:
        """Return model name."""
        return self._model.name

    def save_weights(self, path: str):
        """Save model weights to given path.

        Parameters
        ---------------------------
        path: str,
            Path where to save model weights.
        """
        self._model.save_weights(path)

    def load_weights(self, path: str):
        """Load model weights from given path.

        Parameters
        ---------------------------
        path: str,
            Path from where to load model weights.
        """
        self._model.load_weights(path)
