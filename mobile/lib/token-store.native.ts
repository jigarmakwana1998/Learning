import * as SecureStore from "expo-secure-store";

const KEY = "learning-coach-token";
export const getToken = () => SecureStore.getItemAsync(KEY);
export const setToken = (token: string) => SecureStore.setItemAsync(KEY, token);
export const clearToken = () => SecureStore.deleteItemAsync(KEY);
