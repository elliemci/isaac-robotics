import { useCallback } from 'react';
import { useStreaming } from '../streaming/StreamingProvider';
import { R17_COMMAND_EVENT, isNonemptyRequestId, type R17CommandEnvelope } from '../types/r17';

function createRequestId(): string {
  const cryptoId = globalThis.crypto?.randomUUID?.();
  return cryptoId || `r17-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

export function useR17CommandSender() {
  const { sendMessage } = useStreaming();

  const sendR17Command = useCallback(
    (command: string, payload: Record<string, unknown> = {}) => {
      const requestId = createRequestId();
      if (!isNonemptyRequestId(requestId) || !command.trim()) return null;
      const envelope: R17CommandEnvelope = {
        event_type: R17_COMMAND_EVENT,
        payload: { requestId, command, payload },
      };
      return sendMessage(envelope) ? requestId : null;
    },
    [sendMessage],
  );

  return { sendR17Command };
}
