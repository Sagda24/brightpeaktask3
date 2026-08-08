import faiss
import numpy as np


class VectorStore:
    """
    Vector database layer for RAG.

    Contains:
    1. ANN vector index using HNSW
    2. Metadata payload store
    3. Metadata indexes for filtering
    """

    def __init__(self, dimension):
        self.dimension = dimension

        # Real ANN index: HNSW
        self.index = faiss.IndexHNSWFlat(
            dimension,
            32
        )

        self.index.hnsw.efSearch = 64

        # Metadata payload store
        self.payloads = []

        # Metadata indexes
        self.metadata_index = {
            "document_id": {},
            "category": {},
            "department": {}
        }

    def add(self, embeddings, chunks):
        """
        Add vectors and their metadata/payloads.
        """

        embeddings = np.asarray(
            embeddings,
            dtype="float32"
        )

        self.index.add(embeddings)

        for chunk in chunks:

            index_id = len(self.payloads)

            self.payloads.append(chunk)

            for field in self.metadata_index:

                value = chunk.get(field)

                if value is None:
                    continue

                if value not in self.metadata_index[field]:
                    self.metadata_index[field][value] = []

                self.metadata_index[field][value].append(index_id)

    def _get_allowed_ids(self, metadata_filter):
        """
        Use metadata index BEFORE vector search.
        """

        if not metadata_filter:
            return None

        candidate_sets = []

        for field, value in metadata_filter.items():

            if field not in self.metadata_index:
                return set()

            ids = self.metadata_index[field].get(
                value,
                []
            )

            candidate_sets.append(set(ids))

        if not candidate_sets:
            return None

        allowed = candidate_sets[0]

        for candidate_set in candidate_sets[1:]:
            allowed = allowed.intersection(candidate_set)

        return allowed

    def search(
        self,
        query_embedding,
        top_k=3,
        metadata_filter=None
    ):
        """
        ANN similarity search with optional metadata filtering.
        """

        query_embedding = np.asarray(
            query_embedding,
            dtype="float32"
        )

        allowed_ids = self._get_allowed_ids(
            metadata_filter
        )

        # No filter
        if allowed_ids is None:

            distances, indices = self.index.search(
                query_embedding,
                min(top_k, self.index.ntotal)
            )

        else:

            if not allowed_ids:
                return []

            # Search enough candidates then filter.
            search_k = min(
                max(top_k * 5, 20),
                self.index.ntotal
            )

            distances, indices = self.index.search(
                query_embedding,
                search_k
            )

            filtered = []

            for distance, index_id in zip(
                distances[0],
                indices[0]
            ):

                if index_id in allowed_ids:

                    filtered.append(
                        (float(distance), int(index_id))
                    )

                if len(filtered) == top_k:
                    break

            return [
                {
                    "score": distance,
                    **self.payloads[index_id]
                }
                for distance, index_id in filtered
            ]

        results = []

        for distance, index_id in zip(
            distances[0],
            indices[0]
        ):

            if index_id == -1:
                continue

            results.append({
                "score": float(distance),
                **self.payloads[index_id]
            })

        return results