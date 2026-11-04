import { useEffect, useRef, useState } from "react";
import { deleteDocument, getDocuments, uploadDocument, type DocumentRecord } from "../session/api";

// Your material: the files the answer agent may quote from. Each one is cut into chunks and indexed on this Mac.
export function DocumentsScreen() {
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  async function refresh() {
    try {
      setDocuments(await getDocuments());
      setError(null);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    }
  }

  useEffect(() => { refresh(); }, []);

  async function onFiles(files: FileList | null) {
    if (!files) return;
    for (const file of Array.from(files)) {
      setBusy(`Indexing ${file.name}`);
      try {
        await uploadDocument(file);
      } catch (failure) {
        setError(`${file.name}: ${failure instanceof Error ? failure.message : String(failure)}`);
      }
    }
    setBusy(null);
    if (input.current) input.current.value = "";
    await refresh();
  }

  async function remove(document: DocumentRecord) {
    setBusy(`Removing ${document.name}`);
    await deleteDocument(document.docId);
    setBusy(null);
    await refresh();
  }

  return (
    <div className="screen">
      <p className="muted">
        Add the documents you want answers drawn from: notes, reports, papers, slides as PDF. PDF, Markdown, text and Word files up to 20 MB.
        They are indexed on this Mac and never leave it.
      </p>
      <div className="row">
        <input ref={input} type="file" multiple accept=".pdf,.md,.txt,.docx" data-field="file-input" onChange={(e) => onFiles(e.target.files)} />
      </div>
      {busy && <p className="muted" data-field="busy">{busy}</p>}
      {error && <p className="error">{error}</p>}
      <ul className="documents" data-field="documents">
        {documents.length === 0 && !busy && <li className="muted">No documents yet.</li>}
        {documents.map((document) => (
          <li key={document.docId} className="document">
            <span className="document-name">{document.name}</span>
            <span className="muted">{document.chunkCount} chunk{document.chunkCount === 1 ? "" : "s"}</span>
            <button type="button" className="link" onClick={() => remove(document)}>Remove</button>
          </li>
        ))}
      </ul>
    </div>
  );
}
