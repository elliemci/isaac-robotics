import { useCallback, useState } from 'react';
import type { ReactNode } from 'react';
import { useR17CommandSender } from '../hooks/useR17CommandSender';
import { useR17StateSubscription } from '../hooks/useR17StateSubscription';
import type { R17StatePayload } from '../types/r17';

type R17CommandButtonProps = {
  command: string;
  payload?: Record<string, unknown>;
  disabled?: boolean;
  onRequestStart?: (requestId: string) => void;
  onRequestState?: (state: R17StatePayload) => void;
  children: ReactNode;
};

type Presentation = 'idle' | 'pending' | 'success' | 'error';

function presentationFromState(state: R17StatePayload): Presentation {
  if (state.status === 'WAITING' || state.status === 'APPLYING') return 'pending';
  if (state.status === 'READY') return 'success';
  return 'error';
}

export function R17CommandButton({
  command,
  payload = {},
  disabled = false,
  onRequestStart,
  onRequestState,
  children,
}: R17CommandButtonProps) {
  const { sendR17Command } = useR17CommandSender();
  const [requestId, setRequestId] = useState<string | null>(null);
  const [presentation, setPresentation] = useState<Presentation>('idle');
  const [message, setMessage] = useState('');

  const handleState = useCallback((state: R17StatePayload) => {
    setPresentation(presentationFromState(state));
    setMessage(state.error || state.message || state.status);
    onRequestState?.(state);
    if (state.status === 'READY' || state.status === 'ERROR') {
      setRequestId(null);
    }
  }, [onRequestState]);

  useR17StateSubscription(requestId, handleState);

  const onClick = useCallback(() => {
    if (disabled || requestId) return;
    const nextRequestId = sendR17Command(command, payload);
    if (!nextRequestId) return;
    setRequestId(nextRequestId);
    setPresentation('pending');
    setMessage('');
    onRequestStart?.(nextRequestId);
  }, [command, disabled, onRequestStart, payload, requestId, sendR17Command]);

  return (
    <button
      type="button"
      className={`r17-command-button r17-command-button--${presentation}`}
      disabled={disabled || Boolean(requestId)}
      onClick={onClick}
      aria-busy={Boolean(requestId) || presentation === 'pending'}
      title={message || undefined}
    >
      {children}
    </button>
  );
}
