import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  AppState,
  Linking,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { buildCourse, Course, CourseVersion, getCourse, getCourseVersions, getMe, getResearchActivity, getResearchRun, getResearchRuns, login, logout, register, ResearchActivity, ResearchHistoryItem, ResearchRun, Sentence, startResearchRun, User } from "@/lib/api";

function openPublicUrl(url: string) {
  if (!url.startsWith("https://")) return;
  Linking.openURL(url).catch(() => Alert.alert("Could not open this source."));
}

/** Opens the source page scrolled to the quoted text (a URL text fragment). */
function quoteLink(url: string, quote: string) {
  return `${url.split("#")[0]}#:~:text=${encodeURIComponent(quote).replace(/-/g, "%2D")}`;
}

export default function HomeScreen() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [topic, setTopic] = useState("");
  const [hours, setHours] = useState("5");
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(false);
  const [run, setRun] = useState<ResearchRun | null>(null);
  const [history, setHistory] = useState<ResearchHistoryItem[]>([]);
  const [connectionError, setConnectionError] = useState(false);

  useEffect(() => { getMe().then(setUser).catch(() => undefined); }, []);

  useEffect(() => { if (user) getResearchRuns().then(setHistory).catch(() => setConnectionError(true)); }, [user]);

  useEffect(() => {
    if (run?.status !== "running") return;
    const refresh = () => getResearchRun(run.id).then((next) => { setRun(next); setConnectionError(false); if (next.status !== "running") getResearchRuns().then(setHistory).catch(() => undefined); }).catch(() => setConnectionError(true));
    const timer = setInterval(refresh, 2000);
    const subscription = AppState.addEventListener("change", (state) => { if (state === "active") refresh(); });
    return () => { clearInterval(timer); subscription.remove(); };
  }, [run?.id, run?.status]);

  async function signIn(mode: "login" | "register") {
    setLoading(true);
    try {
      setUser(await (mode === "login" ? login(email, password) : register(email, password)));
    } catch (error) {
      Alert.alert("Authentication failed", error instanceof Error ? error.message : "Try again.");
    } finally {
      setLoading(false);
    }
  }

  async function generatePlan() {
    if (topic.trim().length < 2) {
      Alert.alert("Tell us what you want to learn.");
      return;
    }
    setLoading(true);
    try {
      setRun(await getResearchRun((await startResearchRun(topic.trim(), Number(hours) || 5)).id));
      setHistory(await getResearchRuns());
    } catch (error) {
      Alert.alert("Could not research this topic", error instanceof Error ? error.message : "Please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
        <Text style={styles.eyebrow}>LEARNING COACH</Text>
        <Text style={styles.title}>Learn from evidence, not filler.</Text>

        {!user ? (
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Sign in to research a topic</Text>
            <TextInput value={email} onChangeText={setEmail} placeholder="Email" autoCapitalize="none" keyboardType="email-address" style={styles.input} />
            <TextInput value={password} onChangeText={setPassword} placeholder="Password (8+ characters)" secureTextEntry style={styles.input} />
            <Pressable accessibilityRole="button" onPress={() => signIn("login")} style={({ pressed }) => [styles.primaryButton, pressed && styles.pressed]}>
              {loading ? <ActivityIndicator color="#fff" /> : <Text style={styles.primaryButtonText}>Sign in</Text>}
            </Pressable>
            <Pressable accessibilityRole="button" onPress={() => signIn("register")} style={({ pressed }) => [styles.textButton, pressed && styles.pressed]}>
              <Text style={styles.link}>Create an account</Text>
            </Pressable>
          </View>
        ) : (
          <>
            <View style={styles.userRow}>
              <Text style={styles.signedIn} numberOfLines={1}>Signed in as {user.email}</Text>
              <Pressable accessibilityRole="button" onPress={() => logout().then(() => { setUser(null); setRun(null); setHistory([]); setConnectionError(false); })} style={styles.textButton}><Text style={styles.link}>Sign out</Text></Pressable>
            </View>
            <Text style={styles.subtitle}>Name the subject. The research agent maps what it involves and finds pages that teach each part, reading every page first.</Text>
            <TextInput value={topic} onChangeText={setTopic} placeholder="e.g. Attention layers in large language models" style={styles.input} />
            <Text style={styles.label}>Study time each week</Text>
            <TextInput value={hours} onChangeText={setHours} keyboardType="number-pad" style={styles.input} />
            <Pressable accessibilityRole="button" onPress={generatePlan} disabled={loading} style={({ pressed }) => [styles.primaryButton, pressed && styles.pressed, loading && styles.disabled]}>
              {loading ? <ActivityIndicator color="#fff" /> : <Text style={styles.primaryButtonText}>Research this topic</Text>}
            </Pressable>

            <View style={styles.card}><Text style={styles.cardTitle}>Your research</Text>
              {history.length ? history.map((item) => <Pressable key={item.id} accessibilityRole="button" onPress={() => getResearchRun(item.id).then(setRun).catch(() => setConnectionError(true))} style={styles.textButton}><Text style={styles.link}>{item.topic} · {item.status}</Text></Pressable>) : <Text style={styles.bodyMuted}>Your research sessions will appear here.</Text>}
              {connectionError && <Text accessibilityRole="alert" style={styles.error}>Could not update research. Check your connection and try again.</Text>}
            </View>

            {run && (
              <View style={styles.courseShell}>
                <Text style={styles.cardTitle}>{run.topic}</Text>
                {run.status === "running" && <View style={styles.visitHeader}><ActivityIndicator color="#6657d9" /><Text style={[styles.bodyMuted, styles.signedIn]} numberOfLines={2}>{run.activity ?? "Planning what to cover..."}</Text></View>}
                {run.status === "failed" && <Text style={styles.error}>{run.error ?? "Research failed. Please try again."}</Text>}
                <CoverageList run={run} />
              </View>
            )}
            {run && <ActivityHistory key={run.id} runId={run.id} running={run.status === "running"} />}
            {run?.status === "completed" && <CourseSection key={run.id} researchRunId={run.id} />}
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function ActivityHistory({ runId, running }: { runId: string; running: boolean }) {
  const [data, setData] = useState<ResearchActivity | null>(null);
  const [error, setError] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => {
    const refresh = () => getResearchActivity(runId).then((result) => { setData(result); setError(false); }).catch(() => setError(true));
    refresh();
    if (!running) return;
    const timer = setInterval(refresh, 5000);
    return () => clearInterval(timer);
  }, [runId, running]);
  return <View style={styles.card}><Text style={styles.cardTitle}>Research activity</Text>
    {error && <Text accessibilityRole="alert" style={styles.error}>Could not load research activity.</Text>}
    {data?.sessions.map((session) => <View key={session.id} style={styles.sectionStack}>
      <Text style={styles.label}>{session.agent_name} · {session.status}</Text>
      {session.activity.map((item, i) => {
        const key = `${session.id}-${i}`;
        const pages = (item.output.results ?? item.output.pages ?? []) as Array<Record<string, unknown>>;
        return <View key={key}><Pressable accessibilityRole="button" accessibilityState={{ expanded: open === key }} onPress={() => setOpen(open === key ? null : key)}><Text style={styles.link}>{item.tool === "browser_search" ? `Search: ${String(item.input.query ?? "Query unavailable")}` : "Pages read"}</Text></Pressable>
          {open === key && pages.map((page, j) => <View key={j} style={styles.module}>
            {typeof page.url === "string" && page.url.startsWith("https://") ? <Pressable accessibilityRole="link" onPress={() => openPublicUrl(page.url as string)}><Text style={styles.sourceLinkText}>{String(page.title || page.url)}</Text></Pressable> : <Text>{String(page.title || page.requested_url || "Page unavailable")}</Text>}
            {typeof page.content === "string" && <Text style={styles.paragraph}>{page.content}</Text>}
          </View>)}
        </View>;
      })}
      {session.output != null && <View><Pressable accessibilityRole="button" accessibilityState={{ expanded: open === session.id }} onPress={() => setOpen(open === session.id ? null : session.id)}><Text style={styles.link}>Agent output</Text></Pressable>{open === session.id && <Text style={styles.paragraph}>{JSON.stringify(session.output, null, 2)}</Text>}</View>}
    </View>)}
  </View>;
}

function CoverageList({ run }: { run: ResearchRun }) {
  return (
    <View style={styles.sectionStack}>
      {run.coverage.map((item) => {
        const pages = run.pages.filter((page) => page.covers.includes(item.id));
        return (
          <View key={item.id} style={styles.module}>
            <Text style={styles.kicker}>{item.status.toUpperCase()}</Text>
            <Text style={styles.sectionTitle}>{item.question}</Text>
            {pages.length ? pages.map((page) => (
              <View key={page.url} style={styles.lesson}>
                <Pressable accessibilityRole="link" onPress={() => openPublicUrl(page.url)} style={({ pressed }) => [styles.sourceLink, pressed && styles.pressed]}>
                  <Text style={styles.sourceLinkText}>{page.title}</Text>
                  <Text style={styles.urlText} numberOfLines={2}>{page.url}</Text>
                </Pressable>
                <Text style={styles.bodyMuted}>{page.why}</Text>
                {page.key_points.map((point) => <Text key={point} style={styles.bullet}>• {point}</Text>)}
              </View>
            )) : <Text style={styles.empty}>{run.status === "running" ? "Looking for pages..." : "No page found for this."}</Text>}
          </View>
        );
      })}
    </View>
  );
}

function CourseSection({ researchRunId }: { researchRunId: string }) {
  const [versions, setVersions] = useState<CourseVersion[]>([]);
  const [course, setCourse] = useState<Course | null>(null);
  const [starting, setStarting] = useState(false);

  const show = (id: string) => getCourse(id).then(setCourse);
  const refresh = () => getCourseVersions(researchRunId).then((list) => { setVersions(list); return list; });
  useEffect(() => { refresh().then((list) => list[0] && show(list[0].id)).catch(() => undefined); }, [researchRunId]);

  // Poll while the agent writes so sections appear as they arrive.
  useEffect(() => {
    if (course?.status !== "running") { refresh().catch(() => undefined); return; }
    const refreshCourse = () => show(course.id).catch(() => undefined);
    const timer = setInterval(refreshCourse, 2000);
    const subscription = AppState.addEventListener("change", (state) => { if (state === "active") refreshCourse(); });
    return () => { clearInterval(timer); subscription.remove(); };
  }, [course?.id, course?.status]);

  async function start() {
    setStarting(true);
    try {
      await show((await buildCourse(researchRunId)).id);
    } catch (error) {
      Alert.alert("Could not build the course", error instanceof Error ? error.message : "Please try again.");
    } finally {
      setStarting(false);
    }
  }

  const busy = starting || course?.status === "running";
  return (
    <View style={styles.courseShell}>
      <Text style={styles.cardTitle}>Course</Text>
      <Pressable accessibilityRole="button" onPress={start} disabled={busy} style={({ pressed }) => [styles.primaryButton, pressed && styles.pressed, busy && styles.disabled]}>
        {busy ? <ActivityIndicator color="#fff" /> : <Text style={styles.primaryButtonText}>{versions.length ? "Build new version" : "Build course"}</Text>}
      </Pressable>
      {versions.length > 0 && <ScrollView horizontal contentContainerStyle={styles.versionRow}>
        {versions.map((v) => <Pressable key={v.id} accessibilityRole="button" accessibilityState={{ selected: v.id === course?.id }} onPress={() => show(v.id).catch(() => Alert.alert("Could not load the course"))} style={[styles.versionChip, v.id === course?.id && styles.versionChipActive]}>
          <Text style={v.id === course?.id ? styles.versionTextActive : styles.versionText}>v{v.version} · {v.status}</Text>
        </Pressable>)}
      </ScrollView>}
      {course && <CourseBody course={course} />}
    </View>
  );
}

function CourseBody({ course }: { course: Course }) {
  const source = (passage: string) => course.sources.find((item) => item.id === passage.split(".")[0]);
  return (
    <View style={styles.sectionStack}>
      {course.status === "running" && <View style={styles.visitHeader}><ActivityIndicator color="#6657d9" /><Text style={[styles.bodyMuted, styles.signedIn]} numberOfLines={2}>{course.activity ?? "Reading the sources..."}</Text></View>}
      {course.status === "failed" && <Text style={styles.error}>{course.error ?? "The course could not be built."}</Text>}
      {course.chapters.map((chapter, c) => (
        <View key={chapter.id} style={styles.module}>
          <Text style={styles.kicker}>CHAPTER {c + 1}</Text>
          <Text style={styles.sectionTitle}>{chapter.title}</Text>
          {chapter.sections.map((section) => (
            <View key={section.id} style={styles.lesson}>
              <Text style={styles.label}>{section.title}</Text>
              {course.sections[section.id]?.map((paragraph, p) => <CourseParagraph key={p} sentences={paragraph} source={source} />)
                ?? <Text style={styles.empty}>{course.status === "running" ? "Writing..." : "Not written."}</Text>}
            </View>
          ))}
        </View>
      ))}
      {course.gaps.length > 0 && <View style={styles.module}><Text style={styles.label}>Not covered by the sources</Text>{course.gaps.map((gap) => <Text key={gap} style={styles.bullet}>• {gap}</Text>)}</View>}
      {course.sources.length > 0 && <View style={styles.module}><Text style={styles.label}>Sources</Text>{course.sources.map((item) => (
        <Pressable key={item.id} accessibilityRole="link" onPress={() => openPublicUrl(item.url)} style={styles.sourceLink}><Text style={styles.sourceLinkText}>{item.id.slice(1)}. {item.title}</Text></Pressable>
      ))}</View>}
    </View>
  );
}

function CourseParagraph({ sentences, source }: { sentences: Sentence[]; source: (passage: string) => Course["sources"][number] | undefined }) {
  return (
    <View style={styles.module}>
      <Text style={styles.paragraph}>{sentences.map((sentence, i) => (
        <Text key={i} style={sentence.warning ? styles.warned : undefined}>
          {sentence.text}
          {sentence.cites.map((cite, k) => {
            const page = source(cite.passage);
            return page ? <Text key={k} accessibilityRole="link" onPress={() => openPublicUrl(quoteLink(page.url, cite.quote))} style={styles.cite}> [{cite.passage.slice(1).split(".")[0]}]</Text> : null;
          })}{" "}
        </Text>
      ))}</Text>
      {sentences.filter((s) => s.warning).map((s, i) => <Text key={i} style={styles.warningText}>⚠ {s.warning} ({s.text})</Text>)}
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: "#f7f7fb" },
  container: { padding: 20, paddingBottom: 48, gap: 12 },
  eyebrow: { color: "#6657d9", fontWeight: "800", letterSpacing: 1 },
  title: { fontSize: 32, lineHeight: 38, fontWeight: "800", color: "#1d1b2e" },
  subtitle: { color: "#686579", fontSize: 16, lineHeight: 24, marginVertical: 8 },
  label: { fontWeight: "700", color: "#332f46", marginTop: 4 },
  input: { backgroundColor: "#fff", borderColor: "#ddd9ea", borderWidth: 1, borderRadius: 12, paddingHorizontal: 14, minHeight: 50, fontSize: 16 },
  primaryButton: { backgroundColor: "#6657d9", borderRadius: 12, minHeight: 52, alignItems: "center", justifyContent: "center", marginTop: 4, paddingHorizontal: 16 },
  primaryButtonText: { color: "#fff", fontWeight: "800", fontSize: 16 },
  textButton: { minHeight: 44, justifyContent: "center", paddingHorizontal: 4 },
  pressed: { opacity: 0.72 },
  disabled: { opacity: 0.55 },
  card: { backgroundColor: "#fff", borderRadius: 16, padding: 16, marginTop: 12, gap: 10, borderWidth: 1, borderColor: "#eceaf3" },
  cardTitle: { fontSize: 22, lineHeight: 28, fontWeight: "800", color: "#1d1b2e" },
  link: { color: "#5647cc", fontWeight: "800", textAlign: "center" },
  userRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: 8 },
  signedIn: { flex: 1, color: "#332f46" },
  courseShell: { backgroundColor: "#fff", borderRadius: 18, padding: 16, marginTop: 16, gap: 16, borderWidth: 1, borderColor: "#e6e3ef" },
  sectionStack: { gap: 20 },
  module: { gap: 10 },
  kicker: { color: "#6657d9", fontSize: 12, fontWeight: "800", letterSpacing: 0.7 },
  sectionTitle: { fontSize: 19, lineHeight: 25, fontWeight: "800", color: "#28243b" },
  bodyMuted: { color: "#686579", fontSize: 15, lineHeight: 23 },
  lesson: { borderTopWidth: 1, borderTopColor: "#eceaf3", paddingTop: 18, gap: 10 },
  sourceLink: { minHeight: 44, justifyContent: "center", borderLeftWidth: 2, borderLeftColor: "#8b7fe5", paddingLeft: 10 },
  sourceLinkText: { color: "#4b3fc1", fontSize: 14, lineHeight: 20, fontWeight: "700" },
  urlText: { color: "#5f58a8", fontSize: 12, lineHeight: 18, marginTop: 2 },
  bullet: { color: "#3e394e", fontSize: 14, lineHeight: 21 },
  empty: { backgroundColor: "#f3f1f7", borderRadius: 12, padding: 14, color: "#686579", lineHeight: 21 },
  visitHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: 8 },
  error: { backgroundColor: "#fff0f0", borderColor: "#d45b5b", borderWidth: 1, borderRadius: 12, padding: 14 },
  versionRow: { gap: 8 },
  versionChip: { minHeight: 44, justifyContent: "center", borderRadius: 12, paddingHorizontal: 14, backgroundColor: "#f3f1f7" },
  versionChipActive: { backgroundColor: "#6657d9" },
  versionText: { color: "#332f46", fontWeight: "700" },
  versionTextActive: { color: "#fff", fontWeight: "700" },
  paragraph: { color: "#28243b", fontSize: 16, lineHeight: 25 },
  cite: { color: "#4b3fc1", fontWeight: "700" },
  warned: { backgroundColor: "#fdecc8" },
  warningText: { color: "#8a5a00", fontSize: 12, lineHeight: 18 },
});
