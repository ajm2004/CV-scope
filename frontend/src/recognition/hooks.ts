import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useRecognitionAuth } from "../lib/recognitionToken";

export function useRecognitionStatus() {
  return useQuery({ queryKey: ["recognition-status"], queryFn: api.recognition.status, refetchInterval: 30_000, retry: 0 });
}

export function usePrincipal() {
  const token = useRecognitionAuth((s) => s.token);
  return useQuery({ queryKey: ["recognition-me", token], queryFn: api.recognition.me, enabled: !!token, retry: 0 });
}

export const ENROLLMENT_VIEWS: { id: string; label: string; instruction: string; biometric: boolean }[] = [
  { id: "front", label: "Front", instruction: "Face the camera straight, eyes open, plain expression. Required.", biometric: true },
  { id: "left", label: "Left angle", instruction: "Turn the head slightly to the left, about 30 degrees, eyes still visible.", biometric: true },
  { id: "right", label: "Right angle", instruction: "Turn the head slightly to the right, about 30 degrees, eyes still visible.", biometric: true },
  { id: "above", label: "From slightly above", instruction: "Camera a little above eye level, as a ceiling camera would see the person.", biometric: true },
  { id: "below", label: "From slightly below", instruction: "Camera a little below eye level.", biometric: true },
  { id: "lighting", label: "Different lighting", instruction: "A second front view under different lighting, for example near a window or under artificial light.", biometric: true },
  { id: "rear", label: "Rear / back view", instruction: "Appearance reference only, for tracking continuity. No face and no biometric template are taken from it.", biometric: false },
];

export const EVENT_KIND_LABEL: Record<string, string> = {
  recognized: "Person recognized",
  possible_match: "Possible match",
  identity_changed: "Identity changed",
  identity_cleared: "Identity cleared",
  plate_read: "Plate read",
  registered_vehicle: "Registered vehicle",
  plate_changed: "Plate changed",
};

export const RESULT_LABEL: Record<string, string> = {
  unresolved: "Not decided",
  recognized: "Recognized",
  possible_match: "Possible match",
  unknown: "Unknown",
  insufficient_quality: "Insufficient quality",
};
