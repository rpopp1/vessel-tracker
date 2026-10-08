import type { Notice as NoticeModel } from "../notice";

export default function Notice({ notice }: { notice: NoticeModel | null }) {
  if (!notice) return null;
  return (
    <div className={`notice ${notice.kind}`} role={notice.kind === "error" ? "alert" : "status"}>
      {notice.text}
    </div>
  );
}
