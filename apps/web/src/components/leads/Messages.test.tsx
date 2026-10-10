import type { ConversationOut } from "@approvalready/shared-types";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { Conversation, CustomerMessages } from "./Messages";

const apiRequest = vi.fn();

vi.mock("@/lib/client-api", () => ({
  apiRequest: (...args: unknown[]) => apiRequest(...args),
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
