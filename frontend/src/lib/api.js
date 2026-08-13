import axios from "axios";

const BASE = process.env.REACT_APP_BACKEND_URL;
export const API = `${BASE}/api`;

export const api = axios.create({ baseURL: API, timeout: 10000 });

export async function fetchState() {
  const { data } = await api.get("/state");
  return data;
}

export async function fetchEfficiency() {
  const { data } = await api.get("/efficiency");
  return data;
}

export async function fetchScenarios() {
  const { data } = await api.get("/scenarios");
  return data;
}

export async function setScenario(scenario) {
  const { data } = await api.post("/scenario", { scenario });
  return data;
}

export async function ackAlert(alertId) {
  const { data } = await api.post(`/alerts/${encodeURIComponent(alertId)}/ack`);
  return data;
}

export async function ackAll() {
  const { data } = await api.post(`/alerts/ack-all`);
  return data;
}
