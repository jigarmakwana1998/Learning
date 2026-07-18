import { useEffect, useState } from "react";
import { Link, useLocalSearchParams } from "expo-router";
import { ActivityIndicator, SafeAreaView, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { getTranscript, TranscriptSession } from "@/lib/api";

export default function TranscriptScreen() {
  const { id } = useLocalSearchParams<{ id: string }>(); const [session, setSession] = useState<TranscriptSession | null>(null); const [error, setError] = useState(""); const [query, setQuery] = useState("");
  useEffect(() => { if (id) getTranscript(id).then(setSession).catch(e => setError(e instanceof Error ? e.message : "Unable to load transcript")); }, [id]);
  const entries = session?.transcript.filter(entry => entry.content.toLowerCase().includes(query.toLowerCase())) ?? [];
  return <SafeAreaView style={styles.safe}><ScrollView contentContainerStyle={styles.container}><Link href="/admin" style={styles.link}>← Analytics</Link>{!session && !error ? <ActivityIndicator/> : error ? <Text>{error}</Text> : <><Text style={styles.title}>{session?.agent_name} transcript</Text><TextInput value={query} onChangeText={setQuery} placeholder="Search transcript" style={styles.input}/>{entries.map((entry, index) => <View key={index} style={styles.entry}><Text style={styles.role}>{entry.role}</Text><Text selectable>{entry.content}</Text></View>)}</>}</ScrollView></SafeAreaView>;
}
const styles=StyleSheet.create({safe:{flex:1,backgroundColor:"#f7f7fb"},container:{padding:20,gap:12},link:{color:"#6657d9",fontWeight:"700"},title:{fontSize:26,fontWeight:"800"},input:{backgroundColor:"#fff",borderRadius:12,padding:12,borderColor:"#ddd9ea",borderWidth:1},entry:{backgroundColor:"#fff",borderRadius:12,padding:14,gap:6},role:{fontWeight:"800",textTransform:"uppercase",color:"#6657d9"}});
