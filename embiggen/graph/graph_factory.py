import logging
from typing import Dict
import json
import numpy as np  # type: ignore
import pandas as pd  # type: ignore

from ..utils import logger
from .csv_utils import check_consistent_lines
from .graph import Graph
from .graph_types import numpy_nodes_colors_type, numpy_edges_colors_type
from tqdm.auto import tqdm


class GraphFactory:

    def __init__(
        self,
        default_node_type: str = 'biolink:NamedThing',
        default_edge_type: str = 'biolink:Association',
        verbose: bool = False,
        **kwargs: Dict
    ):
        """Create new GraphFactory object.

        This object has the task of handling the creation of Graph objects,
        handling all the mess that is unifying the various types of CSVs.

        DO NOT add paths to the Graph class: all paths must be handles here.

        Parameters
        ----------------------------
        default_weight: int = 1,
            The default weight for the node when no weight column is given
        default_node_type: str = 'biolink:NamedThing',
            The default type for the nodes when no node type column is given.
        default_edge_type: str = 'biolink:Association',
            The default type for the edges when no edge type column is given.
        verbose: bool = False,
            If to log with INFO level or with CRITICAL.
        **kwargs: Dict
            The kwargs to pass directly to the constructor of the Graph.

        Returns
        -----------------------------
        Return new GraphFactory.
        """
        self._default_node_type = default_node_type
        self._default_edge_type = default_edge_type
        self._kwargs = kwargs
        self._verbose = verbose

        if verbose:
            logger.setLevel(logging.INFO)
        else:
            logger.setLevel(logging.CRITICAL)

    def read_csv(
        self,
        edge_path: str,
        node_path: str = None,
        edge_sep: str = "\t",
        node_sep: str = "\t",
        edge_file_has_header: bool = True,
        node_file_has_header: bool = True,
        start_nodes_column: str = "subject",
        end_nodes_column: str = "object",
        node_types_column: str = "category",
        edge_types_column: str = "edge_label",
        weights_column: str = "weight",
        nodes_columns: str = "id",
        check_for_rows_consistency: bool = True,
        check_for_duplicates: bool = True,
        **kwargs: Dict
    ):
        """Return new instance of graph based on given files.

        Parameters
        -----------------------
        edge_path: str,
            Path to the edges file.
        node_path: str = None,
            Path to the nodes file.
        edge_sep: str = "\t",
            Separator to use for the edges file.
        node_sep: str = "\t",
            Separator to use for the nodes file.
        edge_file_has_header: bool = True,
            Whetever to edge files has a header or not.
        node_file_has_header: bool = True,
            Whetever to node files has a header or not.
        start_nodes_column: str = "subject",
            Column to use for the starting nodes. When no header is available,
            use the numeric index curresponding to the column.
        end_nodes_column: str = "object",
            Column to use for the ending nodes. When no header is available,
            use the numeric index curresponding to the column.
        node_types_column: str = "category",
            Column to use for the nodes type. When no header is available,
            use the numeric index curresponding to the column.
        directed: bool = True,
            Wethever the graph is directed or not. An undirected graph will
            be rendered in the factory before being processed.
        weights_column: str = "weight",
            Column to use for the edges weight. When no header is available,
            use the numeric index curresponding to the column.
        nodes_columns: str = "id",
            Column to use to load the node names, when the node_path argument
            is provided. Parameter is ignored otherwise.
        check_for_rows_consistency: bool = True,
            Wethever to check for rows consistency or not. User MUST provide
            in all cases the input files with rows consistency. This flag is
            only provided to avoid checking this aspect on input files when
            the user is SURE that the input file has consistent rows.
            Consider setting this flag to False when input files are very big.
        check_for_duplicates: bool = True,
            Wethever to check for duplicates or not. User MUST provide in all
            cases the input files without duplicates, this flag is only provided
            to avoid checking this aspect on input files when the user is SURE
            that the input files do not contain duplicates.
            Consider setting this flag to False when input files are very big.
        **kwargs: Dict,
            Additional keyword arguments to pass to the instantiation of a new
            graph object.

        Raises
        ----------------------
        ValueError,
            If the provided edges file have malformed lines.
        ValueError,
            If the provided nodes file have malformed lines.
        ValueError,
            If the nodes in the nodes file are duplicated.
        ValueError,
            If the edges file contains node that do not appear in the nodes file.

        Returns
        ----------------------
        New instance of Graph
        """
        if check_for_rows_consistency:
            logger.info("Checking for rows consistency.")
            check_consistent_lines(edge_path, edge_sep, self._verbose)
            if node_path is not None:
                check_consistent_lines(node_path, node_sep, self._verbose)

        logger.info("Loading edge file")

        header = (0 if edge_file_has_header else None)
        tmp_edges_df = pd.read_csv(
            edge_path,
            sep=edge_sep,
            header=header,
            nrows=1
        )
        use_columns = [
            column
            for column in (
                start_nodes_column, end_nodes_column,
                edge_types_column, weights_column
            )
            if column is not None and column in tmp_edges_df.columns
        ]
        edges_df = pd.read_csv(
            edge_path,
            sep=edge_sep,
            usecols=use_columns,
            dtype={
                start_nodes_column: str,
                end_nodes_column: str,
                edge_types_column: str,
                weights_column: np.float64
            },
            header=header
        )

        if check_for_duplicates:
            logger.info("Checking for duplicates in edge dataframe.")

            # Dropping duplicated edges
            unique_columns = [
                start_nodes_column, end_nodes_column
            ]
            if edge_types_column in edges_df.columns:
                unique_columns.append(edge_types_column)

            #edges_df = edges_df.drop_duplicates(unique_columns)
            duplicated_rows_mask = edges_df.duplicated(unique_columns)
            if duplicated_rows_mask.any():
                raise ValueError(
                    (
                        "There are {} duplicated rows within given edge file "
                        "at path {}. Please drop these rows during preprocessing. "
                        "An example of duplicated line is:\n{}"
                    ).format(
                        duplicated_rows_mask.sum(),
                        edge_path,
                        edges_df.loc[duplicated_rows_mask.argmax()
                                    ].to_json(indent=4)
                    )
                )

        edges = edges_df[[
            start_nodes_column, end_nodes_column
        ]].values.astype(str)

        unique_nodes = np.unique(edges)

        if node_path is not None:
            logger.info("Loading nodes file")

            tmp_nodes_df = pd.read_csv(
                node_path,
                sep=node_sep,
                header=(0 if node_file_has_header else None),
                nrows=1
            )
            nodes_df = pd.read_csv(
                node_path,
                sep=node_sep,
                usecols=[
                    column
                    for column in (
                        nodes_columns,
                        node_types_column
                    )
                    if column is not None and column in tmp_nodes_df.columns
                ],
                dtype={
                    nodes_columns: str,
                    node_types_column: str
                },
                header=(0 if node_file_has_header else None)
            )
            nodes = nodes_df[nodes_columns].values.astype(str)

            # Checking if the nodes from edges are contained in nodes file.
            # We create a set since hashing has a O(1) access time.
            nodes_set = set(nodes)
            for node in tqdm(
                unique_nodes,
                desc="Checking nodes and edges compatibility",
                disable=not self._verbose
            ):
                if node not in nodes_set:
                    raise ValueError((
                        "Edge node {} does not appear "
                        "in the given nodes set."
                    ).format(
                        node
                    ))

            uniques, counts = np.unique(nodes, return_counts=True)

            if len(uniques) != len(nodes):
                raise ValueError((
                    "There are {} duplicate nodes "
                    "in the given nodes file.\n"
                    "The node file is at path {}.\n"
                    "A sample of the duplicates are: \n{}"
                ).format(
                    len(nodes) - len(nodes_set),
                    node_path,
                    json.dumps(uniques[counts>1][:5].tolist(), indent=4),
                ))
        else:
            nodes = unique_nodes

        #######################################
        # Handling edge weights               #
        #######################################

        if weights_column in edges_df.columns:
            weights = edges_df[weights_column].values
        else:
            weights = np.empty(0, dtype=np.float64)

        #######################################
        # Handling node types                 #
        #######################################

        if node_path is not None and node_types_column in nodes_df.columns:
            # If provided, we use the list from the dataframe.
            nodes_df[node_types_column].fillna(
                value=self._default_node_type,
                inplace=True
            )

            node_types = nodes_df[node_types_column].values.astype(str)

            unique_node_types = {
                node_type: np.int16(i)
                for i, node_type in enumerate(tqdm(
                    np.unique(node_types),
                    desc="Search unique node types",
                    disable=not self._verbose
                ))
            }

            numba_node_types = np.empty(
                len(node_types), dtype=numpy_nodes_colors_type)
            for i, node_type in enumerate(tqdm(
                node_types,
                desc="Mapping node types",
                disable=not self._verbose
            )):
                numba_node_types[i] = unique_node_types[node_type]

        else:
            # Otherwise if the column is not available.
            numba_node_types = np.empty(0, dtype=numpy_nodes_colors_type)

        #######################################
        # Handling edge types                 #
        #######################################

        # If provided, we use the list from the dataframe.
        if edge_types_column in edges_df.columns:
            edges_df[edge_types_column].fillna(
                value=self._default_edge_type,
                inplace=True
            )
            edge_types = edges_df[edge_types_column].values.astype(str)

            unique_edge_types = {
                edge_type: i
                for i, edge_type in enumerate(tqdm(
                    np.unique(edge_types),
                    desc="Search unique edge types",
                    disable=not self._verbose
                ))
            }

            numba_edge_types = np.empty(
                len(edge_types), dtype=numpy_edges_colors_type)
            for i, edge_type in enumerate(tqdm(
                edge_types,
                desc="Mapping edge types",
                disable=not self._verbose
            )):
                numba_edge_types[i] = unique_edge_types[edge_type]
        else:
            # Otherwise if the column is not available.
            numba_edge_types = np.empty(0, dtype=numpy_edges_colors_type)

        logger.info("Done preprocessing graph files.")
        logger.info("Starting graph build.")

        return Graph(
            nodes=nodes,
            sources_names=edges_df[start_nodes_column].values.astype(nodes.dtype),
            destinations_names=edges_df[end_nodes_column].values.astype(nodes.dtype),
            node_types=numba_node_types,
            edge_types=numba_edge_types,
            weights=weights,
            **self._kwargs,
            **kwargs
        )
