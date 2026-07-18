import { View } from "react-native";
import Svg, { Rect } from "react-native-svg";

export function BarChart({ values }: { values: number[] }) {
  const max = Math.max(...values, 1);
  return <View style={{ height: 72 }}><Svg width="100%" height="72" viewBox="0 0 240 72">{values.map((value, index) => <Rect key={index} x={index * 58 + 8} y={68 - (value / max) * 60} width="36" height={(value / max) * 60} rx="5" fill="#6657d9" />)}</Svg></View>;
}
