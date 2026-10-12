async function request<T>(
  path: string,
  method: string,
  body: unknown,
  signal: AbortSignal | undefined,
  decode: (response: Response) => Promise<T>,
): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort(signal?.reason);
  if (signal?.aborted) abort();
  else signal?.addEventListener("abort", abort, { once: true });
  let timedOut = false;
  const timer = setTimeout(
    () => {
      timedOut = true;
      controller.abort();
    },
    method === "GET" ? 15000 : 90000,
  );
  try {
    const response = await fetch(`/api${path}`, {
      method,
      signal: controller.signal,
      headers:
        body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok) {
      const error = await response
        .json()
        .catch(() => ({ detail: `请求失败 (${response.status})` }));
      throw new Error(
        typeof error.detail === "string"
          ? error.detail
          : "输入参数不符合要求，请检查后重试。",
      );
    }
    return await decode(response);
  } catch (error) {
    if (timedOut)
      throw new Error(
        method === "GET"
          ? "读取状态超时，请检查本地服务。"
          : "等待操作结果超时。操作可能仍在后台执行，请检查状态后再决定是否重试。",
      );
    throw error;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}
export function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  return request(
    path,
    method,
    body,
    signal,
    (response) => response.json() as Promise<T>,
  );
}
export async function downloadBackup(workspace = false) {
  const blob = await request(
    workspace ? "/maintenance/workspace-backup" : "/maintenance/backup",
    "POST",
    undefined,
    undefined,
    (response) => response.blob(),
  );
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `spark-${workspace ? "workspace" : "evidence"}-${new Date().toISOString().replaceAll(":", "-")}.${workspace ? "zip" : "sqlite"}`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function download(name: string, value: unknown) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
