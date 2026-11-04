# Retrieval pipeline, status notes

## Done this week

The data pipeline for the retrieval experiments is finished. Documents are chunked, embedded and indexed end to end.

## Index build time

The new embedding model cut the index build time from forty minutes to twelve minutes on the full corpus.

## Training run

The last training run used batch size 32 with gradient accumulation of 4 on one GPU.
