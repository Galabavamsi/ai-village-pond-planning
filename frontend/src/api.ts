/**
 * fetch() for the planner's own API with retries on network failures.
 *
 * Some campus networks drop a share of new TCP connections to the IIT host, so
 * a request can fail before reaching the server. Only those network errors are
 * retried; any HTTP response, including an error status, is returned at once.
 */
export async function apiFetch(input: string, init?: RequestInit, attempts = 4): Promise<Response> {
  for (let attempt = 1; ; attempt++) {
    try {
      return await fetch(input, init);
    } catch (error) {
      if (init?.signal?.aborted) throw error;
      if (attempt >= attempts) {
        throw new Error("The planner server could not be reached (network timeout). Check the connection and try again.");
      }
      await new Promise((done) => setTimeout(done, 700 * attempt));
    }
  }
}
