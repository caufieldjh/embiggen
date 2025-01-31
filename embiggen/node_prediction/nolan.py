"""Model implementing Node Label Neighbour for graphs."""
from typing import Dict, Tuple, Union

import numpy as np
import pandas as pd
from ensmallen_graph import EnsmallenGraph
from extra_keras_metrics import get_minimal_multiclass_metrics
from keras_mixed_sequence import MixedSequence, VectorSequence
from sklearn.preprocessing import RobustScaler
from tensorflow.keras import regularizers
from tensorflow.keras.layers import (
    Dense,
    Dropout,
    Embedding,
    Concatenate,
    GlobalAveragePooling1D,
    BatchNormalization,
    Input
)
from tensorflow.keras.models import Model
from tqdm.keras import TqdmCallback
from tensorflow.keras.losses import CategoricalCrossentropy
from tensorflow.keras.optimizers import Optimizer

from ..sequences import NodeLabelNeighboursSequence
from ..embedders import Embedder


class NoLaN(Embedder):
    """Class implementing NoLaN.

    NoLaN is a Node-Label Neighbours model for graphs.

    """

    def __init__(
        self,
        graph: EnsmallenGraph,
        labels_number: int = None,
        node_embedding_size: int = None,
        use_node_embedding_dropout: bool = True,
        node_embedding_dropout_rate: float = 0.4,
        use_node_features_dropout: bool = True,
        node_features_dropout_rate: float = 0.7,
        use_batch_normalization: bool = True,
        l1_kernel_regularization: float = 1e-3,
        l2_kernel_regularization: float = 1e-3,
        hidden_dense_layers: Union[int, Tuple[int]] = (),
        node_embedding: Union[np.ndarray, pd.DataFrame] = None,
        node_features: Union[np.ndarray, pd.DataFrame] = None,
        optimizer: Union[str, Optimizer] = "nadam",
        trainable_node_embedding: bool = False,
        support_mirror_strategy: bool = False,
        scaler: "Scaler" = "RobustScaler"
    ):
        """Create new NoLaN model.

        Parameters
        -------------------
        TODO!
        """
        self._graph = graph
        self._labels_number = self._graph.get_node_types_number(
        ) if labels_number is None else labels_number
        self._use_node_embedding_dropout = use_node_embedding_dropout
        self._node_embedding_dropout_rate = node_embedding_dropout_rate
        self._use_node_features_dropout = use_node_features_dropout
        self._node_features_dropout_rate = node_features_dropout_rate
        self._use_batch_normalization = use_batch_normalization
        self._support_mirror_strategy = support_mirror_strategy
        self._l1_kernel_regularization = l1_kernel_regularization
        self._l2_kernel_regularization = l2_kernel_regularization
        if isinstance(hidden_dense_layers, int):
            hidden_dense_layers = (hidden_dense_layers, )
        self._hidden_dense_layers = hidden_dense_layers

        if scaler == "RobustScaler":
            scaler = RobustScaler()

        if node_embedding is not None:
            if not isinstance(node_embedding, (pd.DataFrame, np.ndarray)):
                raise ValueError(
                    (
                        "The parameter node_embedding can be either None, ",
                        "a numpy array or a pandas dataframe. The one provided ",
                        "has type {}."
                    ).format(
                        type(node_embedding)
                    )
                )
            scaled_node_embedding = scaler.fit_transform(node_embedding)
            if isinstance(node_embedding, pd.DataFrame):
                node_embedding = pd.DataFrame(
                    scaled_node_embedding,
                    columns=node_embedding.columns,
                    index=node_embedding.index,
                )

        self._node_features_size = None

        if node_features is not None:
            if not isinstance(node_features, (pd.DataFrame, np.ndarray)):
                raise ValueError(
                    (
                        "The parameter node_features can be either None, ",
                        "a numpy array or a pandas dataframe. The one provided ",
                        "has type {}."
                    ).format(
                        type(node_features)
                    )
                )
            if node_embedding is not None:
                if isinstance(node_features, pd.DataFrame) != isinstance(node_embedding, pd.DataFrame):
                    raise ValueError(
                        "Node embedding and node features must either be both "
                        "pandas DataFrames or both numpy arrays."
                    )
                if node_features.shape[0] != node_embedding.shape[0]:
                    raise ValueError(
                        (
                            "Given node features must be available"
                            " for each of the {} nodes.".format(
                                node_embedding.shape[0]
                            )
                        )
                    )
                if isinstance(node_features, pd.DataFrame) and (node_features.index != node_embedding.index).any():
                    raise ValueError(
                        (
                            "Index of node features and node embedding must match!\n"
                            "The first values of the features index are {} while the first value sof the node embedding index are {}."
                        ).format(
                            node_features.index[:10],
                            node_embedding.index[:10]
                        )
                    )
            if scaler is not None:
                scaled_node_features = scaler.fit_transform(node_features)
                if isinstance(node_features, pd.DataFrame):
                    node_features = pd.DataFrame(
                        scaled_node_features,
                        columns=node_features.columns,
                        index=node_features.index,
                    )
            self._node_features_size = node_features.shape[1]
        self._node_features = node_features

        super().__init__(
            vocabulary_size=graph.get_nodes_number() if node_embedding is None else None,
            embedding_size=node_embedding_size if node_embedding is None else None,
            embedding=node_embedding,
            optimizer=optimizer,
            trainable_embedding=trainable_node_embedding
        )

    def _build_model(self):
        """Return NoLaN model."""
        node_star_input = Input((None,), name="NodeStarInput")

        node_embedding_layer = Embedding(
            input_dim=self._vocabulary_size+1,
            output_dim=self._embedding_size,
            weights=None if self._embedding is None else [np.vstack([
                np.zeros(self._embedding_size),
                self._embedding
            ])],
            mask_zero=True,
            name=Embedder.EMBEDDING_LAYER_NAME
        )

        mean_node_star_embedding = GlobalAveragePooling1D(
            name="MeanNodeStarEmbedding"
        )(
            node_embedding_layer(node_star_input),
            mask=node_embedding_layer.compute_mask(node_star_input),
        )

        mean_node_star_embedding = BatchNormalization()(mean_node_star_embedding)

        if self._use_node_embedding_dropout:
            mean_node_star_embedding = Dropout(
                self._node_embedding_dropout_rate,
                name="NodeEmbeddingDropout"
            )(mean_node_star_embedding)

        if self._node_features is not None:
            node_features_layer = Embedding(
                input_dim=self._vocabulary_size+1,
                output_dim=self._node_features_size,
                weights=None if self._embedding is None else [np.vstack([
                    np.zeros(self._node_features_size),
                    self._node_features
                ])],
                mask_zero=True,
                trainable=False,
                name="NodeFeatures"
            )

            mean_node_star_features = GlobalAveragePooling1D(
                name="MeanNodeStarFeatures"
            )(
                node_features_layer(node_star_input),
                mask=node_features_layer.compute_mask(node_star_input),
            )

            mean_node_star_features = BatchNormalization()(mean_node_star_features)

            if self._use_node_features_dropout:
                mean_node_star_features = Dropout(
                    self._node_features_dropout_rate,
                    name="NodeFeaturesDropout"
                )(mean_node_star_features)

            mean_node_star_embedding = Concatenate(
                name="NodedataConcatenation"
            )([
                mean_node_star_embedding,
                mean_node_star_features
            ])

        hidden = mean_node_star_embedding

        for units in self._hidden_dense_layers:
            hidden = Dense(
                units,
                activation="relu",
                kernel_regularizer=regularizers.l1_l2(
                    l1=self._l1_kernel_regularization,
                    l2=self._l2_kernel_regularization
                ),
            )(hidden)

        output = Dense(
            self._labels_number,
            kernel_regularizer=regularizers.l1_l2(
                l1=self._l1_kernel_regularization,
                l2=self._l2_kernel_regularization
            ),
            activation="softmax"
        )(hidden)

        model = Model(
            inputs=node_star_input,
            outputs=output,
            name="NoLaN"
        )

        return model

    def _compile_model(self) -> Model:
        """Compile model."""
        self._model.compile(
            optimizer=self._optimizer,
            loss=CategoricalCrossentropy(label_smoothing=0.1),
            metrics=get_minimal_multiclass_metrics()
        )

    def build_training_sequence(
        self,
        train_graph: EnsmallenGraph,
        max_neighbours: int = None,
        batch_size: int = 256,
        validation_graph: EnsmallenGraph = None,
        include_central_node: bool = True,
        random_state: int = 42
    ) -> Tuple[MixedSequence, MixedSequence]:
        """Return .

        Parameters
        --------------------
        train_graph: EnsmallenGraph,
            Training graph.
        max_neighbours: int = None,
            Number of neighbours to consider.
            If None, the graph median is used.
        batch_size: int = 256,
            Batch size for the sequence.
        validation_graph: EnsmallenGraph = None,
            The graph whose nodes are to be predicted.
        include_central_node: bool = True,
            Whether to include the central nodes.
        random_state: int = 42,
            Random seed to reproduce.

        Returns
        --------------------
        Training and validation MixedSequence
        """
        train_sequence = NodeLabelNeighboursSequence(
            train_graph,
            max_neighbours=max_neighbours,
            batch_size=batch_size,
            random_state=random_state,
            include_central_node=include_central_node,
            support_mirror_strategy=self._support_mirror_strategy
        )
        if validation_graph is not None:
            validation_sequence = NodeLabelNeighboursSequence(
                validation_graph,
                max_neighbours=validation_graph.max_degree(),
                batch_size=batch_size,
                random_state=random_state,
                support_mirror_strategy=self._support_mirror_strategy
            )
        else:
            validation_sequence = None
        return train_sequence, validation_sequence

    def fit(
        self,
        train_graph: EnsmallenGraph,
        max_neighbours: int = None,
        include_central_node: bool = True,
        batch_size: int = 256,
        epochs: int = 1000,
        validation_graph: EnsmallenGraph = None,
        early_stopping_monitor: str = "loss",
        early_stopping_min_delta: float = 0,
        early_stopping_patience: int = 20,
        early_stopping_mode: str = "min",
        reduce_lr_monitor: str = "loss",
        reduce_lr_min_delta: float = 0,
        reduce_lr_patience: int = 5,
        reduce_lr_mode: str = "min",
        reduce_lr_factor: float = 0.9,
        verbose: int = 1,
        random_state: int = 42,
        **kwargs: Dict
    ) -> pd.DataFrame:
        """Return pandas dataframe with training history.

        Parameters
        -----------------------
        train_graph: EnsmallenGraph,
            Training graphs.
        max_neighbours: int = None,
            Number of neighbours to consider.
            If None, the graph median is used.
        include_central_node: bool = True,
            Whether to include the central node.
        epochs: int = 10000,
            Epochs to train the model for.
        validation_graph: EnsmallenGraph = None,
            Data reserved for validation.
        early_stopping_monitor: str = "loss",
            Metric to monitor for early stopping.
        early_stopping_min_delta: float = 0.1,
            Minimum delta of metric to stop the training.
        early_stopping_patience: int = 5,
            Number of epochs to wait for when the given minimum delta is not
            achieved after which trigger early stopping.
        early_stopping_mode: str = "min",
            Direction of the variation of the monitored metric for early stopping.
        reduce_lr_monitor: str = "loss",
            Metric to monitor for reducing learning rate.
        reduce_lr_min_delta: float = 1,
            Minimum delta of metric to reduce learning rate.
        reduce_lr_patience: int = 3,
            Number of epochs to wait for when the given minimum delta is not
            achieved after which reducing learning rate.
        reduce_lr_mode: str = "min",
            Direction of the variation of the monitored metric for learning rate.
        reduce_lr_factor: float = 0.9,
            Factor for reduction of learning rate.
        verbose: int = 1,
            Wethever to show the loading bar.
            Specifically, the options are:
            * 0 or False: No loading bar.
            * 1 or True: Showing only the loading bar for the epochs.
            * 2: Showing loading bar for both epochs and batches.
        **kwargs: Dict,
            Additional kwargs to pass to the Keras fit call.

        Returns
        -----------------------
        Dataframe with training history.
        """
        train_sequence, validation_sequence = self.build_training_sequence(
            train_graph,
            max_neighbours=max_neighbours,
            include_central_node=include_central_node,
            batch_size=batch_size,
            validation_graph=validation_graph,
            random_state=random_state
        )
        return super().fit(
            train_sequence,
            epochs=epochs,
            validation_data=validation_sequence,
            early_stopping_monitor=early_stopping_monitor,
            early_stopping_min_delta=early_stopping_min_delta,
            early_stopping_patience=early_stopping_patience,
            early_stopping_mode=early_stopping_mode,
            reduce_lr_monitor=reduce_lr_monitor,
            reduce_lr_min_delta=reduce_lr_min_delta,
            reduce_lr_patience=reduce_lr_patience,
            reduce_lr_mode=reduce_lr_mode,
            reduce_lr_factor=reduce_lr_factor,
            verbose=verbose,
            **kwargs
        )

    def predict(
        self,
        graph_to_predict: EnsmallenGraph,
        verbose: bool = False,
        batch_size=256,
        random_state: int = 42
    ):
        """Run predict."""
        return self._model.predict(
            NodeLabelNeighboursSequence(
                graph_to_predict,
                max_neighbours=graph_to_predict.max_degree(),
                batch_size=batch_size,
                shuffle=False,
                random_state=random_state,
                support_mirror_strategy=self._support_mirror_strategy
            ),
            verbose=verbose
        )

    def evaluate(
        self,
        graph_to_evaluate: EnsmallenGraph,
        validation_graph: EnsmallenGraph = None,
        verbose: bool = False,
        batch_size=256,
        random_state: int = 42
    ) -> pd.DataFrame:
        """Run predict.

        TODO! Update docstring!
        """
        train_sequence, validation_sequence = self.build_training_sequence(
            graph_to_evaluate,
            max_neighbours=self._graph.max_degree(),
            batch_size=batch_size,
            validation_graph=validation_graph,
            random_state=random_state
        )
        return pd.DataFrame(
            [{
                **dict(zip(
                    self._model.metrics_names,
                    self._model.evaluate(
                        train_sequence,
                        verbose=verbose
                    )
                )),
                "run_type": "training"
            },
                *(({
                    **dict(zip(
                        self._model.metrics_names,
                        self._model.evaluate(
                            validation_sequence,
                            verbose=verbose
                        )
                    )),
                    "run_type": "validation"
                }, ) if validation_sequence is not None
                else ()
            )]
        )

    @property
    def embedding(self) -> np.ndarray:
        """Return model embeddings.

        Raises
        -------------------
        NotImplementedError,
            If the current embedding model does not have an embedding layer.
        """
        # We need to drop the first column (feature) of the embedding
        # curresponding to the indices 0, as this value is reserved for the
        # masked values. The masked values are the values used to fill
        # the batches of the neigbours of the nodes.
        return Embedder.embedding.fget(self)[1:]  # pylint: disable=no-member

    def get_embedding_dataframe(self) -> pd.DataFrame:
        """Return terms embedding using given index names."""
        return super().get_embedding_dataframe(self._graph.get_node_names())
