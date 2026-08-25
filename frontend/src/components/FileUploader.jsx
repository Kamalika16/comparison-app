import { useCallback, useRef, useState } from "react";

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
      <div className="file-uploader__label">{label}</div>
      {file ? (
        <div className="file-uploader__filename">{file.name}</div>
      ) : (
        <div className="file-uploader__hint">Drag & drop, or click to browse (.xlsx, .xls, .csv)</div>
      )}
    </div>
  );
}
