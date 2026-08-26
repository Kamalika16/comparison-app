import { useCallback, useRef, useState } from "react";

/** Small monochrome icons keep the dropzone readable without extra assets. */
const UploadIcon = () => (
  <svg
    width="20"
    height="20"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
    <polyline points="17 8 12 3 7 8" />
    <line x1="12" y1="3" x2="12" y2="15" />
  </svg>
);

const FileIcon = () => (
  <svg
    width="20"
    height="20"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
    <polyline points="14 2 14 8 20 8" />
    <polyline points="9 14 11 16 15 12" />
  </svg>
);

/**
 * Drag-and-drop (or click-to-browse) uploader for a single Excel/CSV file.
 */
export default function FileUploader({ label, file, onFileSelected, accept = ".xlsx,.xls,.csv" }) {
  const [isDragOver, setIsDragOver] = useState(false);
  const inputRef = useRef(null);

  const handleFiles = useCallback(
    (fileList) => {
      const selected = fileList?.[0];
      if (selected) onFileSelected(selected);
    },
    [onFileSelected]
  );

  const onDrop = (e) => {
    e.preventDefault();
    setIsDragOver(false);
    handleFiles(e.dataTransfer.files);
  };

  return (
    <div
      className={`file-uploader ${isDragOver ? "file-uploader--active" : ""} ${file ? "file-uploader--filled" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setIsDragOver(true);
      }}
      onDragLeave={() => setIsDragOver(false)}
      onDrop={onDrop}
      onClick={() => inputRef.current?.click()}
      role="button"
      tabIndex={0}
      aria-label={`${label}: ${file ? file.name : "no file chosen"}`}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") inputRef.current?.click();
      }}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        hidden
        onChange={(e) => handleFiles(e.target.files)}
      />
      <div className="file-uploader__icon" aria-hidden="true">
        {file ? <FileIcon /> : <UploadIcon />}
      </div>
      <div className="file-uploader__label">{label}</div>
      {file ? (
        <>
          <div className="file-uploader__filename">{file.name}</div>
          <div className="file-uploader__hint">Click to choose a different file</div>
        </>
      ) : (
        <>
          <div className="file-uploader__hint">Drag &amp; drop, or click to browse</div>
          <div className="file-uploader__formats">Excel (.xlsx / .xls) or CSV</div>
        </>
      )}
    </div>
  );
}
