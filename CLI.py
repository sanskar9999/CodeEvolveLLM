import re
from groq import Groq
import datetime
import subprocess
import json
import io
import sys
from contextlib import redirect_stdout, redirect_stderr
from typing import List, Dict, Any, Optional

class ChatAppCLI:
    def __init__(self):
        self.client = Groq(api_key='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')
        self.conversation_history: List[Dict[str, str]] = []
        self.max_attempts = 3
        self.best_solution: Dict[str, Any] = {"code": "", "output": "", "success_rate": 0, "attempt": 0}
        self.last_failed_attempt: Optional[Dict[str, Any]] = None

    def get_multiline_input(self, prompt: str) -> str:
        """Reads multi-line input from the user until an empty line is entered."""
        print(prompt)
        lines = []
        while True:
            line = input()
            if not line.strip():
                break
            lines.append(line)
        return "\n".join(lines)

    def summarize_conversation(self) -> str:
        """Uses the LLM to create a concise summary of the conversation."""
        if not self.conversation_history:
            return "No conversation history yet."

        messages = [
            {"role": "system", "content": "Summarize the following conversation, focusing on the user's goal, the code attempts, and any errors encountered. Be extremely concise."},
            *self.conversation_history
        ]

        try:
            response = self.client.chat.completions.create(
                messages=messages,
                model="qwen-2.5-coder-32b",
                temperature=0.2,  # Lower temperature for summarization
                max_tokens=500,  # Limit summary length
                top_p=0.5,
                stop=None,
                stream=False,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"Error during summarization: {e}")
            return "Error summarizing conversation."

    def run_code(self, code_snippet: str) -> Dict[str, Any]:
        """Executes the given code snippet and captures output, errors, and test results."""
        try:
            output_buffer = io.StringIO()
            error_buffer = io.StringIO()

            with redirect_stdout(output_buffer), redirect_stderr(error_buffer):
                namespace: Dict[str, Any] = {}
                exec(code_snippet, namespace)

            output = output_buffer.getvalue()
            error = error_buffer.getvalue()

            success_rate = 0
            if "test_results" in namespace:
                test_results = namespace["test_results"]
                if isinstance(test_results, list):  # Ensure test_results is a list
                    passed = sum(1 for result in test_results if isinstance(result, dict) and result.get("passed"))
                    success_rate = (passed / len(test_results)) * 100 if test_results else 0

            return {
                "success": not error,
                "output": output,
                "error": error,
                "success_rate": success_rate
            }
        except Exception as e:
            return {
                "success": False,
                "output": "",
                "error": str(e),
                "success_rate": 0
            }

    def generate_response(self, user_input: str) -> str:
        """Generates a response from the LLM, including context and instructions."""
        self.conversation_history.append({"role": "user", "content": user_input})

        context_summary = self.summarize_conversation()
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        system_prompt = (
            "You are an EXPERT coding LLM specializing in iterative code refinement. "
            "Your task is to generate, debug, and optimize code through multiple attempts. "
            "Follow these guidelines:\n"
            "1. Use only 1 code block per response, enclosed in triple backticks (```).\n"
            "2. Include complete, executable code with test cases in each attempt.\n"
            "3. Each code block MUST include:\n"
            "   - The main solution/function\n"
            "   - Test cases with expected outputs\n"
            "   - Code to execute tests and print results.\n"
            "   - Store test results in a 'test_results' list with passed/failed status.\n"
            "4. Analyze previous attempts and execution results before generating new code.\n"
            "5. Explain your reasoning and test case selection before providing code.\n"
            "6. If code fails, identify the error and propose fixes.\n"
            "7. If tests fail, analyze patterns and improve the solution.\n"
            "8. If code is slow or suboptimal, suggest optimizations.\n"
            "9. If an approach fails repeatedly, consider alternative solutions.\n"
            "10. When you are satisfied with the solution and it passes all tests, include the token FINAL_ANSWER in your response.\n"
            f"Maximum refinement attempts: {self.max_attempts}\n"
            f"Current date and time: {current_time}"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": f"Context summary:\n{context_summary}"},
        ]

        if self.best_solution["code"]:
            messages.append({
                "role": "system",
                "content": f"Best Solution (Attempt {self.best_solution['attempt']}):\nCode: {self.best_solution['code'][:30]}...\nSuccess Rate: {self.best_solution['success_rate']}%"
            })
        if self.last_failed_attempt:
            messages.append({
                "role": "system",
                "content": f"Last Failed Attempt:\nCode: {self.last_failed_attempt['code'][:30]}...\nError: {self.last_failed_attempt.get('error', 'None')[:30]}...\nSuccess Rate: {self.last_failed_attempt.get('success_rate', 0)}%"
            })

        messages.append({"role": "user", "content": user_input})


        try:
            response = self.client.chat.completions.create(
                messages=messages,
                model="qwen-2.5-coder-32b",
                temperature=0.7,
                max_tokens=2048,  # Adjust as needed
                top_p=0.5,
                stop=None,
                stream=False,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            return f"An error occurred: {e}"

    def process_ai_response(self, ai_response: str) -> bool:
        """Processes the AI's response, executes code, and updates the state."""
        if "FINAL_ANSWER" in ai_response:
            print("\nAI: (Final Answer)\n", ai_response)
            return True  # Stop iteration

        code_match = re.search(r'```(?:python)?\s*(.*?)\s*```', ai_response, re.DOTALL)
        if not code_match:
            self.conversation_history.append({"role": "assistant", "content": ai_response})
            print("\nAI:\n", ai_response)
            return False

        code_snippet = code_match.group(1).strip()
        print("\nGenerated Code:")
        print(code_snippet)

        execution_result = self.run_code(code_snippet)
        print("\nExecution Result:")
        print(f"  Output: {execution_result['output'].strip()}")
        print(f"  Error: {execution_result['error'] or 'None'}")
        print(f"  Success Rate: {execution_result['success_rate']}%")

        if execution_result["success_rate"] == 100:
            print("\nAI: (Achieved 100% Success Rate - Final Answer)\n", ai_response)
            return True

        if execution_result["success_rate"] > self.best_solution["success_rate"]:
            self.best_solution = {
                "code": code_snippet,
                "output": execution_result["output"],
                "success_rate": execution_result["success_rate"],
                "attempt": len(self.conversation_history) // 2 + 1  # Approximate attempt number
            }
        else:
          self.last_failed_attempt = {
                "code": code_snippet,
                "output": execution_result["output"],
                "error": execution_result["error"],
                "success_rate": execution_result["success_rate"]
            }

        self.conversation_history.append({"role": "assistant", "content": ai_response})
        return False

    def run_chat(self):
        """Main loop for the chat application."""
        print("CLI Chat Assistant with Automated Code Refinement (type 'quit' to exit, press Enter twice to finish multi-line input)")
        while True:
            user_input = self.get_multiline_input("\nYou: ")
            if user_input.lower() == 'quit':
                break

            ai_response = self.generate_response(user_input)
            should_stop = self.process_ai_response(ai_response)
            if should_stop:
                self.best_solution = {"code": "", "output": "", "success_rate": 0, "attempt": 0} #reset best solution
                self.last_failed_attempt = None #reset last failed attempt
                continue #go to the next conversation
def main():
    app = ChatAppCLI()
    app.run_chat()

if __name__ == "__main__":
    main() 
