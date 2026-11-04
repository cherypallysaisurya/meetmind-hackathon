# Method: chunking long documents

Documents longer than the model's context window are split into chunks of about three hundred tokens
with an overlap of fifty tokens between consecutive chunks. Each chunk keeps its document name and section.
