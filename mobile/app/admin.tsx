import { useEffect, useMemo, useState } from "react";
import { Link } from "expo-router";
import { ActivityIndicator, Pressable, SafeAreaView, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";

import { BarChart } from "@/components/BarChart";
import { getAgentProvider, getOverview, getSessions, getUsers, setAgentProvider, AgentProvider, AnalyticsOverview, Session, User } from "@/lib/api";

const providers: AgentProvider[] = ["mock", "codex", "gemini-cli", "antigravity-cli"];

export default function AdminScreen() {
  const [overview, setOverview] = useState<AnalyticsOverview | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [provider, setProvider] = useState<AgentProvider>("mock");
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");

  const load = () => Promise.all([getOverview(), getUsers(), getSessions(), getAgentProvider()])
    .then(([currentOverview, currentUsers, currentSessions, setting]) => {
      setOverview(currentOverview); setUsers(currentUsers.items); setSessions(currentSessions); setProvider(setting.provider); setError("");
    })
    .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Unable to load admin data"));

  useEffect(() => { load(); }, []);
  const visibleSessions = useMemo(() => sessions.filter(session => `${session.topic} ${session.agent_name} ${session.provider}`.toLowerCase().includes(query.toLowerCase())), [sessions, query]);
  const chooseProvider = (next: AgentProvider) => setAgentProvider(next).then(result => setProvider(result.provider)).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Unable to update provider"));

  if (!overview && !error) return <SafeAreaView style={styles.center}><ActivityIndicator /></SafeAreaView>;
  return <SafeAreaView style={styles.safe}><ScrollView contentContainerStyle={styles.container}>
    <Link href="/" style={styles.link}>Back to Learning Coach</Link><Text style={styles.title}>Admin analytics</Text>
    {error ? <Text style={styles.error}>{error}</Text> : <>
      <View style={styles.card}><Text style={styles.section}>Default agent provider</Text><Text style={styles.muted}>Changes apply to the next learning run without restarting the API.</Text><View style={styles.providers}>{providers.map(option => <Pressable key={option} onPress={() => chooseProvider(option)} style={[styles.provider, provider === option && styles.providerSelected]}><Text style={provider === option ? styles.providerTextSelected : styles.providerText}>{option}</Text></Pressable>)}</View></View>
      <View style={styles.grid}>{[["Users", overview?.total_users], ["Requests", overview?.total_requests], ["Completed", overview?.completed_runs], ["Transcripts", overview?.transcript_entries]].map(([label, value]) => <View key={String(label)} style={styles.metric}><Text style={styles.metricValue}>{value}</Text><Text>{label}</Text></View>)}</View>
      <View style={styles.card}><Text style={styles.section}>Run outcomes</Text><BarChart values={[overview?.completed_runs ?? 0, overview?.failed_runs ?? 0, overview?.active_sessions ?? 0]} /><Text style={styles.muted}>Completed / Failed / Active sessions</Text></View>
      <View style={styles.card}><Text style={styles.section}>Users ({users.length})</Text>{users.map(user => <Text key={user.id} style={styles.row}>{user.email} / {user.role}</Text>)}</View>
      <TextInput value={query} onChangeText={setQuery} placeholder="Filter sessions by topic, agent, provider" style={styles.input} />
      <View style={styles.card}><Text style={styles.section}>Agent sessions</Text>{visibleSessions.map(session => <Link key={session.id} href={{ pathname: "/session/[id]", params: { id: session.id } }} style={styles.row}>{session.agent_name} / {session.topic} / {session.status}</Link>)}</View>
      <Pressable style={styles.refresh} onPress={load}><Text style={styles.refreshText}>Refresh analytics</Text></Pressable>
    </>}
  </ScrollView></SafeAreaView>;
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: "#f7f7fb" }, center: { flex: 1, alignItems: "center", justifyContent: "center" }, container: { padding: 20, gap: 12 }, title: { fontSize: 30, fontWeight: "800", color: "#1d1b2e" }, grid: { flexDirection: "row", flexWrap: "wrap", gap: 8 }, metric: { width: "48%", backgroundColor: "#fff", padding: 14, borderRadius: 12 }, metricValue: { fontSize: 25, fontWeight: "800", color: "#6657d9" }, card: { backgroundColor: "#fff", borderRadius: 14, padding: 14, gap: 8 }, section: { fontSize: 18, fontWeight: "800" }, row: { paddingVertical: 9, borderBottomWidth: 1, borderColor: "#eee", color: "#332f46" }, input: { backgroundColor: "#fff", borderRadius: 12, padding: 14, borderWidth: 1, borderColor: "#ddd9ea" }, link: { color: "#6657d9", fontWeight: "700" }, muted: { color: "#686579" }, providers: { flexDirection: "row", flexWrap: "wrap", gap: 8 }, provider: { borderWidth: 1, borderColor: "#ddd9ea", paddingVertical: 8, paddingHorizontal: 10, borderRadius: 8 }, providerSelected: { backgroundColor: "#6657d9", borderColor: "#6657d9" }, providerText: { color: "#332f46" }, providerTextSelected: { color: "#fff", fontWeight: "700" }, refresh: { backgroundColor: "#6657d9", borderRadius: 12, padding: 14, alignItems: "center" }, refreshText: { color: "#fff", fontWeight: "700" }, error: { color: "#a40000" },
});
