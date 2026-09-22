import { useState } from "react";

type AvatarSize = "sm" | "md" | "lg";

/**
 * Sizing per variant. `box` is the outer dimension; `text` is the initials
 * size for the fallback. Kept as a single lookup so the two states can't
 * drift in size when a variant is edited.
 */
const SIZES: Record<AvatarSize, { box: string; text: string }> = {
  sm: { box: "h-8 w-8", text: "text-[10px]" },
  md: { box: "h-9 w-9", text: "text-xs" },
  lg: { box: "h-14 w-14", text: "text-sm" },
};

/**
 * Derive 1-2 initials from a display name. Falls back to "??" when the
 * name is empty so the fallback avatar never renders blank.
 */
function computeInitials(name: string | null | undefined): string {
  const trimmed = (name ?? "").trim();
  if (!trimmed) return "??";
  const parts = trimmed.split(/\s+/).filter(Boolean);
  const initials = parts
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  return initials || "??";
}

/**
 * User avatar with graceful fallback to initials.
 *
 * When the profile picture fails to load - a stale URL left over from a
 * pre-migration upload, a missing object in storage, or a transient
 * network failure - the browser fires `onError` on the <img>. Without
 * handling it, the user sees a broken-image icon, which reads as a
 * product bug. This component records the failing URL and renders the
 * initials fallback instead, so a missing picture is indistinguishable
 * from "user has never uploaded one" - the state users already
 * understand.
 *
 * The failed-URL tracking is per-instance and per-URL: if `profilePictureUrl`
 * changes (new upload, different user), the image is attempted again
 * because the new URL won't equal the one that failed.
 */
export function Avatar({
  profilePictureUrl,
  name,
  size = "md",
  bordered = false,
  className,
}: {
  profilePictureUrl: string | null | undefined;
  name: string | null | undefined;
  size?: AvatarSize;
  /** Renders a subtle border around the avatar. Used where the avatar
   * sits on a plain background (settings page) but not where it sits on
   * a tinted one (sidebar trigger). */
  bordered?: boolean;
  className?: string;
}) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const showImage =
    Boolean(profilePictureUrl) && profilePictureUrl !== failedUrl;
  const { box, text } = SIZES[size];
  const border = bordered ? "border border-border" : "";

  if (showImage && profilePictureUrl) {
    return (
      <img
        src={profilePictureUrl}
        alt=""
        onError={() => setFailedUrl(profilePictureUrl)}
        className={`${box} shrink-0 rounded-full object-cover ${border} ${className ?? ""}`.trim()}
      />
    );
  }

  return (
    <span
      aria-hidden="true"
      className={`${box} flex shrink-0 items-center justify-center rounded-full bg-accent-soft font-semibold text-accent-strong ${text} ${border} ${className ?? ""}`.trim()}
    >
      {computeInitials(name)}
    </span>
  );
}