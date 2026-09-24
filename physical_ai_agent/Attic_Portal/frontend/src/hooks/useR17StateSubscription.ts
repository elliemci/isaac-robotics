import { useEffect } from 'react';
import { useStreaming } from '../streaming/StreamingProvider';
import { R17_STATE_EVENT, isR17StatePayload, type R17StatePayload } from '../types/r17';

export function useR17StateFeed(onState: (state: R17StatePayload) => void) {
  const { onCustomEvent } = useStreaming();

  useEffect(() => {
    return onCustomEvent((event) => {
      if (event.event_type !== R17_STATE_EVENT || !isR17StatePayload(event.payload)) return;
      onState(event.payload);
    });
  }, [onCustomEvent, onState]);
}

export function useR17StateSubscription(
  requestId: string | null,
  onState: (state: R17StatePayload) => void,
) {
  const { onCustomEvent } = useStreaming();

  useEffect(() => {
    if (!requestId) return undefined;
    return onCustomEvent((event) => {
      if (event.event_type !== R17_STATE_EVENT || !isR17StatePayload(event.payload)) return;
      if (event.payload.requestId !== requestId) return;
      onState(event.payload);
    });
  }, [onCustomEvent, onState, requestId]);
}
