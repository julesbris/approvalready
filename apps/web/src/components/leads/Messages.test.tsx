import type { ConversationOut, MessageOut } from "@approvalready/shared-types";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { Conversation, CustomerMessages } from "./Messages";

const apiRequest = vi.fn();
const apiUpload = vi.fn();

vi.mock("@/lib/client-api", () => ({
  apiRequest: (...args: unknown[]) => apiRequest(...args),
  apiUpload: (...args: unknown[]) => apiUpload(...args),
}));

function conversation(overrides: Partial<ConversationOut> = {}): ConversationOut {
  return {
    match_id: "m1",
    lead_id: "lead1",
    category_label: "Town planner",
    partner_name: "Reef Planning",
    can_send: true,
    unread: 1,
    messages: [
      {
        id: "a",
        sender: "CUSTOMER",
        from_you: true,
        body: "Can you start in November?",
        sent_at: "2026-10-10T01:00:00Z",
        read_at: "2026-10-10T02:00:00Z",
      },
      {
        id: "b",
        sender: "PARTNER",
        from_you: false,
        body: "Yes, the second week.",
        sent_at: "2026-10-10T03:00:00Z",
        read_at: null,
      },
    ],
    ...overrides,
  };
}

describe("Conversation", () => {
  beforeEach(() => apiRequest.mockReset());

  it("marks unread messages read on opening and sends a reply", async () => {
    const replied = conversation({
      unread: 0,
      messages: [
        ...conversation().messages,
        {
          id: "c",
          sender: "CUSTOMER",
          from_you: true,
          body: "Great, thanks",
          sent_at: "2026-10-10T04:00:00Z",
          read_at: null,
        },
      ],
    });
    apiRequest.mockResolvedValue({ ok: true, data: replied });
    render(
      <Conversation
        conversation={conversation()}
        path="/x/m1"
        otherName="Reef Planning"
        canWrite
      />,
    );

    expect(screen.getByText("Yes, the second week.")).toBeInTheDocument();
    expect(screen.getByText("New")).toBeInTheDocument();
    expect(screen.getByText(/Seen/)).toBeInTheDocument();
    await waitFor(() => expect(apiRequest).toHaveBeenCalledWith("POST", "/x/m1/read"));

    fireEvent.change(screen.getByLabelText("Message to Reef Planning"), {
      target: { value: "  Great, thanks " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() =>
      expect(apiRequest).toHaveBeenCalledWith("POST", "/x/m1/messages", { body: "Great, thanks" }),
    );
    expect(await screen.findByText("Great, thanks")).toBeInTheDocument();
  });

  it("is read-only once the job is finished", () => {
    render(
      <Conversation
        conversation={conversation({ can_send: false, unread: 0 })}
        path="/x/m1"
        otherName="Customer"
        canWrite
      />,
    );
    expect(screen.queryByRole("button", { name: "Send message" })).not.toBeInTheDocument();
    expect(screen.getByText(/conversation is read-only/)).toBeInTheDocument();
    expect(apiRequest).not.toHaveBeenCalled();
  });
});

describe("CustomerMessages", () => {
  it("explains messages before any partner accepts", () => {
    render(<CustomerMessages organisationId="o" projectId="p" conversations={[]} canWrite />);
    expect(screen.getByText(/When a partner accepts your request/)).toBeInTheDocument();
  });
});

describe("Files in messages", () => {
  beforeEach(() => {
    apiRequest.mockReset();
    apiUpload.mockReset();
  });

  const file = {
    id: "f1",
    filename: "site plan.pdf",
    content_type: "application/pdf",
    size_bytes: 2048,
    scan_status: "CLEAN" as const,
  };

  it("links a checked file and labels one still being checked", () => {
    const base = conversation({ unread: 0 });
    const [mine, theirs] = base.messages as [MessageOut, MessageOut];
    render(
      <Conversation
        conversation={{
          ...base,
          messages: [
            { ...mine, attachment: file },
            { ...theirs, attachment: { ...file, id: "f2", scan_status: "PENDING" } },
          ],
        }}
        path="/x/m1"
        otherName="Reef Planning"
        canWrite
      />,
    );
    const links = screen.getAllByRole("link", { name: "site plan.pdf" });
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "/api/v1/x/m1/files/f1/content");
    expect(screen.getByText(/Checking for viruses/)).toBeInTheDocument();
  });

  it("sends a chosen file with the message text", async () => {
    const base = conversation({ unread: 0 });
    const [mine] = base.messages as [MessageOut];
    const sent = {
      ...base,
      messages: [...base.messages, { ...mine, id: "c", body: "The plan", attachment: file }],
    };
    apiUpload.mockResolvedValue({ ok: true, data: sent });
    render(<Conversation conversation={base} path="/x/m1" otherName="Reef Planning" canWrite />);
    const chosen = new File(["%PDF-1.7"], "site plan.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText(/Attach a file/), { target: { files: [chosen] } });
    fireEvent.change(screen.getByLabelText("Message to Reef Planning"), {
      target: { value: "The plan" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send file" }));
    await waitFor(() =>
      expect(apiUpload).toHaveBeenCalledWith("/x/m1/files", chosen, { body: "The plan" }),
    );
    expect(await screen.findByRole("link", { name: "site plan.pdf" })).toBeInTheDocument();
    expect(apiRequest).not.toHaveBeenCalledWith("GET", "/x/m1/messages");
  });
});
