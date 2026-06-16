"use client";

import "@/styles/notfound.scss";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/hooks/useI18n";

interface NotFoundProps {
  statusCode?: number;
  message?: string;
  title?: string;
}

const getStatusCode = (message: string) => {
  const possibleStatusCodes = ["404", "403", "500", "422"];
  const potentialStatusCode = possibleStatusCodes.find((code) =>
    message.includes(code)
  );
  return potentialStatusCode ? parseInt(potentialStatusCode) : undefined;
};

export default function NotFound({
  statusCode,
  message,
  title,
}: NotFoundProps) {
  const { messages } = useI18n();
  const resolvedMessage = message ?? messages.common.pageNotFound;
  const potentialStatusCode = getStatusCode(resolvedMessage);

  return (
    <div className="flex flex-col items-center justify-center h-[calc(100vh-100px)]">
      <div className="site">
        <div className="sketch">
          <div className="bee-sketch red"></div>
          <div className="bee-sketch blue"></div>
        </div>
        <h1>
          {statusCode
            ? `${statusCode}:`
            : potentialStatusCode
            ? `${potentialStatusCode}:`
            : "404"}
          <small>{title || resolvedMessage}</small>
        </h1>
      </div>

      <div className="">
        <Button
          variant="outline"
          className="bg-primary text-foreground hover:bg-primary/80"
        >
          <Link href="/">{messages.common.goHome}</Link>
        </Button>
      </div>
    </div>
  );
}
