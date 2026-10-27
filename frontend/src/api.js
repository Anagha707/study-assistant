const BASE = "http://127.0.0.1:8000/api";

export async function api(path, { method = "GET", body, form } = {}) {
  const headers = {};
  const t = localStorage.getItem("token");
  if (t) headers.Authorization = `Token ${t}`;
  let b;
  if (form) b = form;
  else if (body) {
    headers["Content-Type"] = "application/json";
    b = JSON.stringify(body);
  }
  const res = await fetch(BASE + path, { method, headers, body: b });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(
      data.error || data.non_field_errors?.[0] || data.detail || "Request failed"
    );
  }
  return data;
}
