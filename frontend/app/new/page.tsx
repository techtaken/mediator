import { redirect } from "next/navigation";

/** Starting a conversation now lives on the home page. Kept so old links still work. */
export default function NewRoomPage() {
  redirect("/");
}
