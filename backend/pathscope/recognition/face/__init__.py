"""Face recognition for deliberately enrolled identities.

    Frame -> Person detection (core tracker) -> Face detection -> Face quality
    -> Face alignment -> Embedding model -> Match against enrolled identities
    -> Confidence / similarity check -> Recognition event

Every stage is a separate, replaceable component (``detector``, ``quality``,
``alignment``, ``embeddings``, ``matcher``). Unknown people stay anonymous
tracks; no demographic or other attribute is ever inferred.
"""
