import { useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Linking,
  Pressable,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { Link } from "expo-router";

import {
  createLearningRun,
  getLearningRunTrace,
  getMe,
  LearningRun,
  LearningRunTrace,
  login,
  logout,
  register,
  Source,
  User,
} from "@/lib/api";

type CourseView = "lesson" | "sources" | "trace";

function openPublicUrl(url: string) {
  if (!url.startsWith("https://")) return;
  Linking.openURL(url).catch(() => Alert.alert("Could not open this source."));
}

export default function HomeScreen() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [topic, setTopic] = useState("");
  const [hours, setHours] = useState("5");
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(false);
  const [plan, setPlan] = useState<LearningRun | null>(null);
  const [courseView, setCourseView] = useState<CourseView>("lesson");
  const [trace, setTrace] = useState<LearningRunTrace | null>(null);
  const [traceError, setTraceError] = useState("");

  useEffect(() => { getMe().then(setUser).catch(() => undefined); }, []);

  const sourcesByUrl = useMemo(
    () => new Map((plan?.research.sources ?? []).map((source) => [source.url, source])),
    [plan],
  );

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
      const nextPlan = await createLearningRun(topic.trim(), Number(hours) || 5);
      setPlan(nextPlan);
      setCourseView("lesson");
      setTrace(null);
      setTraceError("");
    } catch (error) {
      Alert.alert("Could not create course", error instanceof Error ? error.message : "Please try again.");
    } finally {
      setLoading(false);
    }
  }

  async function showTrace() {
    setCourseView("trace");
    if (!plan || trace) return;
    setTraceError("");
    try {
      setTrace(await getLearningRunTrace(plan.id));
    } catch (error) {
      setTraceError(error instanceof Error ? error.message : "The transcript could not be loaded.");
    }
  }

  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
        <Text style={styles.eyebrow}>LEARNING COACH</Text>
        <Text style={styles.title}>Learn from evidence, not filler.</Text>

        {!user ? (
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Sign in to build your course</Text>
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
              <Pressable accessibilityRole="button" onPress={() => logout().then(() => setUser(null))} style={styles.textButton}><Text style={styles.link}>Sign out</Text></Pressable>
            </View>
            {user.role === "admin" && <Link href="/admin" style={styles.adminLink}>Open admin analytics</Link>}
            <Text style={styles.subtitle}>Name the subject. The system will discover sources, read and filter them, then write a cited course with quizzes and an assignment.</Text>
            <TextInput value={topic} onChangeText={setTopic} placeholder="e.g. Attention layers in large language models" style={styles.input} />
            <Text style={styles.label}>Study time each week</Text>
            <TextInput value={hours} onChangeText={setHours} keyboardType="number-pad" style={styles.input} />
            <Pressable accessibilityRole="button" onPress={generatePlan} disabled={loading} style={({ pressed }) => [styles.primaryButton, pressed && styles.pressed, loading && styles.disabled]}>
              {loading ? <ActivityIndicator color="#fff" /> : <Text style={styles.primaryButtonText}>Research and create my course</Text>}
            </Pressable>

            {plan && (
              <View style={styles.courseShell}>
                <Text style={styles.cardTitle}>{plan.research.topic}</Text>
                <View accessibilityRole="tablist" style={styles.tabs}>
                  <Tab active={courseView === "lesson"} label="Lessons" onPress={() => setCourseView("lesson")} />
                  <Tab active={courseView === "sources"} label="Sources" onPress={() => setCourseView("sources")} />
                  <Tab active={courseView === "trace"} label="Agent trace" onPress={showTrace} />
                </View>

                {courseView === "lesson" && <LessonList plan={plan} sourcesByUrl={sourcesByUrl} />}
                {courseView === "sources" && <SourceLedger plan={plan} />}
                {courseView === "trace" && <TracePanel trace={trace} error={traceError} onRetry={showTrace} />}
              </View>
            )}
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function Tab({ active, label, onPress }: { active: boolean; label: string; onPress: () => void }) {
  return (
    <Pressable accessibilityRole="tab" accessibilityState={{ selected: active }} onPress={onPress} style={({ pressed }) => [styles.tab, active && styles.activeTab, pressed && styles.pressed]}>
      <Text style={[styles.tabText, active && styles.activeTabText]}>{label}</Text>
    </Pressable>
  );
}

function LessonList({ plan, sourcesByUrl }: { plan: LearningRun; sourcesByUrl: Map<string, Source> }) {
  return (
    <View style={styles.sectionStack}>
      {plan.curriculum.map((module) => (
        <View key={module.week} style={styles.module}>
          <Text style={styles.kicker}>MODULE {module.week}</Text>
          <Text style={styles.sectionTitle}>{module.title}</Text>
          {module.overview ? <Text style={styles.bodyMuted}>{module.overview}</Text> : null}
          {(module.lessons ?? []).map((lesson) => (
            <View key={lesson.id} style={styles.lesson}>
              <Text style={styles.lessonTitle}>{lesson.title}</Text>
              <Text style={styles.objective}>{lesson.objective}</Text>
              {(lesson.paragraphs ?? []).map((paragraph, index) => (
                <View key={`${lesson.id}-${index}`} style={styles.paragraph}>
                  <Text selectable style={styles.body}>{paragraph.text}</Text>
                  <Text style={styles.citationLabel}>Sources for this paragraph</Text>
                  {paragraph.source_urls.map((url) => (
                    <Pressable key={url} accessibilityRole="link" onPress={() => openPublicUrl(url)} style={({ pressed }) => [styles.sourceLink, pressed && styles.pressed]}>
                      <Text style={styles.sourceLinkText}>{sourcesByUrl.get(url)?.title ?? url}</Text>
                      <Text style={styles.urlText} numberOfLines={2}>{url}</Text>
                    </Pressable>
                  ))}
                </View>
              ))}
              <View style={styles.practice}>
                <Text style={styles.practiceTitle}>Practice</Text>
                <Text style={styles.body}>{lesson.practice}</Text>
              </View>
            </View>
          ))}
        </View>
      ))}
      <View style={styles.practice}>
        <Text style={styles.practiceTitle}>Assignment</Text>
        <Text style={styles.lessonTitle}>{plan.assessment.assignment.title}</Text>
        <Text style={styles.body}>{plan.assessment.assignment.prompt}</Text>
        <Text style={styles.citationLabel}>Deliverables</Text>
        {plan.assessment.assignment.deliverables.map((item) => <Text key={item} style={styles.bullet}>• {item}</Text>)}
        <Text style={styles.citationLabel}>Rubric</Text>
        {plan.assessment.assignment.rubric.map((item) => <Text key={item} style={styles.bullet}>• {item}</Text>)}
        <Text style={styles.practiceTitle}>Project</Text>
        <Text style={styles.body}>{plan.assessment.project}</Text>
      </View>
    </View>
  );
}

function SourceLedger({ plan }: { plan: LearningRun }) {
  const visits = plan.research.visited_sources ?? [];
  const coverage = plan.research.coverage ?? [];
  const coveredCount = coverage.filter((item) => item.status === "covered").length;
  return (
    <View style={styles.sectionStack}>
      <View>
        <Text style={styles.sectionTitle}>Sources used in the course</Text>
        <Text style={styles.bodyMuted}>{plan.research.sources.length} verified source{plan.research.sources.length === 1 ? "" : "s"} grounded the course after reading {visits.filter((item) => item.status === "read").length} pages.</Text>
        {coverage.length ? <Text style={styles.bodyMuted}>Coverage: {coveredCount}/{coverage.length} requirements covered · {plan.research.stop_reason?.replaceAll("_", " ")}</Text> : null}
        {plan.research.warnings?.map((warning) => <Text key={warning} style={styles.error}>{warning}</Text>)}
      </View>
      {plan.research.sources.length ? plan.research.sources.map((source) => (
        <View key={source.url} style={styles.sourceCard}>
          <Text style={styles.kicker}>{source.kind.toUpperCase()}</Text>
          <Pressable accessibilityRole="link" onPress={() => openPublicUrl(source.url)}><Text style={styles.sourceTitle}>{source.title}</Text><Text style={styles.urlText}>{source.url}</Text></Pressable>
          <Text style={styles.bodyMuted}>{source.rationale}</Text>
          {source.key_points?.map((point) => <Text key={point} style={styles.bullet}>• {point}</Text>)}
        </View>
      )) : <Text style={styles.error}>This run has no verified sources and cannot be used as a researched course.</Text>}

      <Text style={styles.sectionTitle}>Every page visited</Text>
      {visits.length ? visits.map((visit, index) => (
        <Pressable key={`${visit.url}-${index}`} accessibilityRole="link" onPress={() => openPublicUrl(visit.url)} style={({ pressed }) => [styles.visit, pressed && styles.pressed]}>
          <View style={styles.visitHeader}><Text style={styles.visitStatus}>{visit.status.toUpperCase()}</Text>{visit.selected && <Text style={styles.selected}>USED</Text>}</View>
          <Text style={styles.sourceTitle}>{visit.title ?? visit.url}</Text>
          <Text style={styles.urlText}>{visit.url}</Text>
        </Pressable>
      )) : <Text style={styles.empty}>No browser visits were recorded.</Text>}
    </View>
  );
}

function TracePanel({ trace, error, onRetry }: { trace: LearningRunTrace | null; error: string; onRetry: () => void }) {
  if (error) return <View style={styles.error}><Text style={styles.errorTitle}>Transcript unavailable</Text><Text style={styles.body}>{error}</Text><Pressable onPress={onRetry} style={styles.secondaryButton}><Text style={styles.secondaryButtonText}>Try again</Text></Pressable></View>;
  if (!trace) return <View style={styles.loading}><ActivityIndicator color="#6657d9" /><Text style={styles.bodyMuted}>Loading every agent session...</Text></View>;
  return (
    <View style={styles.sectionStack}>
      <Text style={styles.bodyMuted}>This is the durable transcript for every research and writing stage. Browser page bodies are intentionally not stored.</Text>
      {trace.sessions.map((session) => (
        <View key={session.id} style={styles.traceSession}>
          <View style={styles.visitHeader}><Text style={styles.sectionTitle}>{session.agent_name}</Text><Text style={styles.visitStatus}>{session.status.toUpperCase()}</Text></View>
          {session.transcript.map((entry, index) => (
            <View key={`${entry.created_at}-${index}`} style={styles.traceEntry}><Text style={styles.kicker}>{entry.role.toUpperCase()}</Text><Text selectable style={styles.traceText}>{entry.content}</Text></View>
          ))}
          {session.tool_invocations.map((tool, index) => (
            <View key={`${tool.created_at}-${index}`} style={styles.toolEntry}>
              <Text style={styles.practiceTitle}>{tool.tool_name} · {tool.status}</Text>
              {tool.metadata?.query ? <Text style={styles.sourceTitle}>{tool.metadata.query}</Text> : null}
              {tool.metadata?.purpose ? <Text style={styles.bodyMuted}>{tool.metadata.purpose}</Text> : null}
              {(tool.metadata?.page_results ?? []).map((page) => <Pressable key={page.url} onPress={() => openPublicUrl(page.url)}><Text style={styles.urlText}>{page.status}: {page.url}</Text></Pressable>)}
              {!(tool.metadata?.page_results?.length) && tool.metadata?.urls?.map((url) => <Text key={url} style={styles.urlText}>{url}</Text>)}
            </View>
          ))}
        </View>
      ))}
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
  secondaryButton: { borderWidth: 1, borderColor: "#6657d9", borderRadius: 10, minHeight: 48, alignItems: "center", justifyContent: "center", marginTop: 12 },
  secondaryButtonText: { color: "#4b3fc1", fontWeight: "800" },
  textButton: { minHeight: 44, justifyContent: "center", paddingHorizontal: 4 },
  pressed: { opacity: 0.72 },
  disabled: { opacity: 0.55 },
  card: { backgroundColor: "#fff", borderRadius: 16, padding: 16, marginTop: 12, gap: 10, borderWidth: 1, borderColor: "#eceaf3" },
  cardTitle: { fontSize: 22, lineHeight: 28, fontWeight: "800", color: "#1d1b2e" },
  link: { color: "#5647cc", fontWeight: "800", textAlign: "center" },
  adminLink: { color: "#4234ae", fontWeight: "800", paddingVertical: 10 },
  userRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: 8 },
  signedIn: { flex: 1, color: "#332f46" },
  courseShell: { backgroundColor: "#fff", borderRadius: 18, padding: 16, marginTop: 16, gap: 16, borderWidth: 1, borderColor: "#e6e3ef" },
  tabs: { flexDirection: "row", flexWrap: "wrap", gap: 8, borderBottomWidth: 1, borderBottomColor: "#eceaf3", paddingBottom: 12 },
  tab: { minHeight: 44, paddingHorizontal: 14, justifyContent: "center", borderRadius: 10 },
  activeTab: { backgroundColor: "#eeeafe" },
  tabText: { color: "#686579", fontWeight: "700" },
  activeTabText: { color: "#4b3fc1" },
  sectionStack: { gap: 20 },
  module: { gap: 10 },
  kicker: { color: "#6657d9", fontSize: 12, fontWeight: "800", letterSpacing: 0.7 },
  sectionTitle: { fontSize: 19, lineHeight: 25, fontWeight: "800", color: "#28243b" },
  bodyMuted: { color: "#686579", fontSize: 15, lineHeight: 23 },
  lesson: { borderTopWidth: 1, borderTopColor: "#eceaf3", paddingTop: 18, gap: 10 },
  lessonTitle: { color: "#1d1b2e", fontSize: 24, lineHeight: 30, fontWeight: "800" },
  objective: { color: "#565166", fontSize: 17, lineHeight: 25 },
  paragraph: { gap: 9, marginTop: 10 },
  body: { color: "#2f2b3f", fontSize: 16, lineHeight: 27 },
  citationLabel: { color: "#332f46", fontSize: 12, fontWeight: "800", marginTop: 3 },
  sourceLink: { minHeight: 44, justifyContent: "center", borderLeftWidth: 2, borderLeftColor: "#8b7fe5", paddingLeft: 10 },
  sourceLinkText: { color: "#4b3fc1", fontSize: 14, lineHeight: 20, fontWeight: "700" },
  urlText: { color: "#5f58a8", fontSize: 12, lineHeight: 18, marginTop: 2 },
  practice: { backgroundColor: "#f2f0fb", borderRadius: 12, padding: 14, gap: 8, marginTop: 8 },
  practiceTitle: { color: "#332f46", fontWeight: "800" },
  sourceCard: { borderBottomWidth: 1, borderBottomColor: "#eceaf3", paddingBottom: 16, gap: 7 },
  sourceTitle: { color: "#4b3fc1", fontSize: 15, lineHeight: 21, fontWeight: "800" },
  bullet: { color: "#3e394e", fontSize: 14, lineHeight: 21 },
  empty: { backgroundColor: "#f3f1f7", borderRadius: 12, padding: 14, color: "#686579", lineHeight: 21 },
  visit: { backgroundColor: "#f8f7fb", borderRadius: 12, padding: 12, minHeight: 64, gap: 5 },
  visitHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: 8 },
  visitStatus: { color: "#686579", fontSize: 11, fontWeight: "800" },
  selected: { color: "#18683a", backgroundColor: "#dcf5e5", borderRadius: 6, overflow: "hidden", paddingHorizontal: 6, paddingVertical: 3, fontSize: 10, fontWeight: "800" },
  error: { backgroundColor: "#fff0f0", borderColor: "#d45b5b", borderWidth: 1, borderRadius: 12, padding: 14 },
  errorTitle: { color: "#812b2b", fontWeight: "800", marginBottom: 4 },
  loading: { minHeight: 120, alignItems: "center", justifyContent: "center", gap: 10 },
  traceSession: { borderWidth: 1, borderColor: "#e6e3ef", borderRadius: 14, padding: 14, gap: 12 },
  traceEntry: { backgroundColor: "#f8f7fb", borderRadius: 10, padding: 12, gap: 6 },
  traceText: { color: "#332f46", fontSize: 13, lineHeight: 20, fontFamily: "monospace" },
  toolEntry: { borderLeftWidth: 2, borderLeftColor: "#8b7fe5", paddingLeft: 10, gap: 5 },
});
