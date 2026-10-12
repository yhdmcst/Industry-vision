import { useEffect, useState } from "react";
import { api } from "./api";
import { useSessionValue } from "./useSessionValue";

interface Listing {
  path: string;
  parent: string;
  entries: { name: string; path: string; directory: boolean }[];
  truncated: boolean;
}
export function PathInput({
  label,
  value,
  onChange,
  directory = false,
  disabled = false,
  placeholder = "",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  directory?: boolean;
  disabled?: boolean;
  placeholder?: string;
}) {
  const [open, setOpen] = useState(false);
  const [folder, setFolder] = useState("");
  const [listing, setListing] = useState<Listing>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [recent, setRecent] = useSessionValue<string[]>(`paths:${label}`, []);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setListing(undefined);
    api<Listing>(
      `/local/paths?path=${encodeURIComponent(folder)}`,
      "GET",
      undefined,
      controller.signal,
    )
      .then(setListing)
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [open, folder]);
  const choose = (path: string) => {
    onChange(path);
    setRecent([path, ...recent.filter((item) => item !== path)].slice(0, 8));
    setOpen(false);
  };
  return (
    <div className="path-input">
      <label>
        {label}
        <input
          aria-label={label}
          required
          value={value}
          disabled={disabled}
          placeholder={placeholder}
          onChange={(e) => onChange(e.target.value)}
        />
      </label>
      <button
        type="button"
        disabled={disabled}
        onClick={() => {
          setOpen(!open);
          setFolder("");
        }}
      >
        浏览本机{directory ? "目录" : "文件"}
      </button>
      {recent.length > 0 && (
        <select
          aria-label={`${label}最近选择`}
          value=""
          disabled={disabled}
          onChange={(e) => choose(e.target.value)}
        >
          <option value="">最近选择…</option>
          {recent.map((path) => (
            <option key={path}>{path}</option>
          ))}
        </select>
      )}
      {open && (
        <div className="path-browser" aria-label={`${label}路径选择`}>
          <p className="muted small">
            选择后端电脑上的路径；最近记录不代表导入成功。
          </p>
          {loading && <p role="status">正在读取目录…</p>}
          {error && (
            <p role="alert" className="notice danger">
              {error}
            </p>
          )}
          {listing && (
            <>
              <p className="path-location">{listing.path}</p>
              <div className="actions">
                <button type="button" onClick={() => setFolder(listing.parent)}>
                  上一级
                </button>
                {directory && (
                  <button type="button" onClick={() => choose(listing.path)}>
                    选择此目录
                  </button>
                )}
              </div>
              <div className="path-entries">
                {listing.entries
                  .filter((entry) => !directory || entry.directory)
                  .map((entry) => (
                    <button
                      type="button"
                      key={entry.path}
                      onClick={() =>
                        entry.directory
                          ? setFolder(entry.path)
                          : choose(entry.path)
                      }
                    >
                      {entry.directory ? "▸ " : ""}
                      {entry.name}
                    </button>
                  ))}
              </div>
              {!listing.entries.length && (
                <p className="muted small">目录为空</p>
              )}
              {listing.truncated && (
                <p>目录项目过多，仅显示前 500 项；可直接输入完整路径。</p>
              )}
            </>
          )}
          <button type="button" onClick={() => setOpen(false)}>
            关闭路径选择
          </button>
        </div>
      )}
    </div>
  );
}
