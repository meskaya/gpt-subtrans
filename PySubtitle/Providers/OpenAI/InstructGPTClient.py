import logging
import time
import openai
from openai.types.completion import Completion

from PySubtitle.Helpers.Parse import ParseDelayFromHeader
from PySubtitle.Providers.OpenAI.OpenAIClient import OpenAIClient
from PySubtitle.SubtitleError import TranslationImpossibleError, TranslationResponseError

linesep = '\n'

class InstructGPTClient(OpenAIClient):
    """
    Handles communication with GPT instruct models to request translations
    """
    def __init__(self, settings : dict):
        settings['supports_conversation'] = False
        settings['supports_system_messages'] = False
        super().__init__(settings)

    @property
    def max_instruct_tokens(self):
        return self.settings.get('max_instruct_tokens', 2048)

    def _send_messages(self, prompt : str, temperature):
        """
        Make a request to the OpenAI API to provide a translation
        """
        response = {}

        for retry in range(self.max_retries + 1):
            if self.aborted:
                return None

            try:
                result : Completion = self.client.completions.create(
                    model=self.model,
                    prompt=prompt,
                    temperature=temperature,
                    n=1,
                    max_tokens=self.max_instruct_tokens
                )

                if self.aborted:
                    return None

                if not isinstance(result, Completion):
                    raise TranslationResponseError(f"Unexpected response type: {type(result).__name__}", response=result)

                response['response_time'] = getattr(result, 'response_ms', 0)

                if result.usage:
                    response['prompt_tokens'] = getattr(result.usage, 'prompt_tokens')
                    response['output_tokens'] = getattr(result.usage, 'completion_tokens')
                    response['total_tokens'] = getattr(result.usage, 'total_tokens')

                if result.choices:
                    choice = result.choices[0]
                    if not isinstance(choice.text, str):
                        raise TranslationResponseError("Instruct model completion text is not a string", response=result)

                    response['finish_reason'] = getattr(choice, 'finish_reason', None)
                    response['text'] = choice.text
                else:
                    raise TranslationResponseError("No choices returned in the response", response=result)

                # Return the response content if the API call succeeds
                return response

            except openai.RateLimitError as e:
                retry_after = e.response.headers.get('x-ratelimit-reset-requests') or e.response.headers.get('Retry-After')
                if retry_after:
                    retry_seconds = ParseDelayFromHeader(retry_after)
                    logging.warning(f"Rate limit hit, retrying in {retry_seconds} seconds...")
                    time.sleep(retry_seconds)
                    continue
                else:
                    logging.warning("Rate limit hit, quota exceeded. Please wait until the quota resets.")
                    raise

            except openai.APITimeoutError as e:
                if retry < self.max_retries and not self.aborted:
                    sleep_time = self.backoff_time * 2.0**retry
                    logging.warning(f"OpenAI error {str(e)}, retrying in {sleep_time}...")
                    time.sleep(sleep_time)
                    continue

            except openai.APIConnectionError as e:
                if not self.aborted:
                    raise TranslationImpossibleError(str(e), error=e)

            except Exception as e:
                raise TranslationImpossibleError(f"Unexpected error communicating with OpenAI", error=e)

        raise TranslationImpossibleError(f"Failed to communicate with provider after {self.max_retries} retries")

