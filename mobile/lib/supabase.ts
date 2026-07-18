import "react-native-url-polyfill/auto";
import { createClient } from "@supabase/supabase-js";

import { clearToken, getToken, setToken } from "@/lib/token-store";

const url = process.env.EXPO_PUBLIC_SUPABASE_URL;
const key = process.env.EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY;

if (!url || !key) throw new Error("EXPO_PUBLIC_SUPABASE_URL and EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY are required.");

export const supabase = createClient(url, key, {
  auth: { storage: { getItem: getToken, setItem: setToken, removeItem: clearToken }, autoRefreshToken: true, persistSession: true, detectSessionInUrl: false },
});
