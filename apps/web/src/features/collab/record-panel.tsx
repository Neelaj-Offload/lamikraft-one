"use client";

import { Tabs } from "@/components/ui/tabs";
import { RecordActivity } from "./activity";
import { RecordAttachments } from "./attachments";
import { RecordNote } from "./notes";

/**
 * Notes, attachments and activity for any record (polymorphic children: the server authorises each through the
 * record itself). Record pages embed it, e.g. `<RecordCollaboration resourceType="sales.quote" resourceId={id} />`.
 */
export function RecordCollaboration({ resourceType, resourceId }: { resourceType: string; resourceId: string }) {
  return (
    <Tabs
      label="Notes, attachments and activity"
      tabs={[
        { id: "note", label: "Note", content: <RecordNote resourceType={resourceType} resourceId={resourceId} /> },
        { id: "files", label: "Attachments", content: <RecordAttachments resourceType={resourceType} resourceId={resourceId} /> },
        { id: "activity", label: "Activity", content: <RecordActivity resourceType={resourceType} resourceId={resourceId} /> },
      ]}
    />
  );
}
