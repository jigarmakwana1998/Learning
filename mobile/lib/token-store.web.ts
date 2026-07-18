const KEY = "learning-coach-token";
export const getToken = async () => globalThis.localStorage?.getItem(KEY) ?? null;
export const setToken = async (token: string) => { globalThis.localStorage?.setItem(KEY, token); };
export const clearToken = async () => { globalThis.localStorage?.removeItem(KEY); };
