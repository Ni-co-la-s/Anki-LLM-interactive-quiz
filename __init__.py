from aqt import mw
from aqt.utils import showText, qconnect, showInfo, showCritical
from aqt.qt import *
import json
import requests
import os
import time
import threading
import sys
from aqt.gui_hooks import card_will_show, webview_did_receive_js_message

# Debug function to help troubleshoot streaming
def debug_print(msg):
    """Print debug messages to console"""
    config = get_config()
    if config.get('debug_mode', False) or os.environ.get('ANKI_LLM_DEBUG'):
        print(f"[LLM Quiz Debug] {msg}", file=sys.stderr)

# Custom exceptions for error handling
class LLMError(Exception):
    """Base exception for LLM-related errors"""
    pass

class ConnectionError(LLMError):
    """Raised when connection to LLM service fails"""
    pass

class APIKeyError(LLMError):
    """Raised when API key is invalid or missing"""
    pass

class ConfigurationError(LLMError):
    """Raised when configuration is invalid"""
    pass

# Get configuration from Anki's config system
def get_config():
    """Get the add-on config from Anki's configuration system"""
    config = mw.addonManager.getConfig(__name__)
    if config is None:
        # If config is None, create default config
        config = {
            "llm_studio_url": "http://localhost:1234/v1/chat/completions",
            "openai_api_key": "",
            "use_openai": False,
            "openai_model": "gpt-3.5-turbo",
            "question_field_index": 0,
            "answer_field_index": 1,
            "timeout": 30,  # Added timeout setting
            "max_retries": 3,  # Added retry setting
            "stream_responses": True,  # Added streaming setting
            "debug_mode": False,  # Added debug setting
            "system_prompt": """You are an interactive quiz assistant for Anki flashcards.

QUESTION: {question}
CORRECT ANSWER: {answer}

IMPORTANT INSTRUCTIONS:
1. Always communicate in English only
2. Be extremely concise - limit each response to 1-3 sentences maximum
3. Present ONLY the question to the student in a clear way first
4. Wait for their response before proceeding
5. Ask only one follow-up question at a time
6. After they've thoroughly attempted to answer, reveal the correct answer briefly
7. Provide very short, specific feedback comparing their answer to the correct one

Remember: Brevity is essential - one point at a time, keep all responses short and focused."""
        }
        save_config(config)
    return config

def save_config(config):
    """Save the config to Anki's configuration system"""
    mw.addonManager.writeConfig(__name__, config)

class ConfigDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("LLM Quiz Configuration")
        self.config = get_config()
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout()
        
        # Create form layout
        form = QFormLayout()
        
        # LM Studio URL
        self.lm_studio_url = QLineEdit(self.config.get("llm_studio_url", "http://localhost:1234/v1/chat/completions"))
        form.addRow("LM Studio URL:", self.lm_studio_url)
        
        # OpenAI settings
        self.use_openai = QCheckBox("Use OpenAI")
        self.use_openai.setChecked(self.config.get("use_openai", False))
        form.addRow("", self.use_openai)
        
        self.openai_key = QLineEdit(self.config.get("openai_api_key", ""))
        self.openai_key.setEchoMode(QLineEdit.EchoMode.Password)  # Hide API key
        form.addRow("OpenAI API Key:", self.openai_key)
        
        self.openai_model = QComboBox()
        self.openai_model.addItems([
            "gpt-5",
            "gpt-5-mini",
            "gpt-5-nano",
            "gpt-4",
            "gpt-4-turbo",
            "gpt-4.1",
            "gpt-4.1-mini",
            "gpt-4.1-nano",
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-3.5-turbo",
            "o1",
            "o1-mini",
            "o1-pro",
            "o1-preview",
            "o3",
            "o3-mini",
            "o3-pro",
            "o4-mini",
        ])
        # Set current selection from config
        current_model = self.config.get("openai_model", "gpt-3.5-turbo")
        if current_model in [self.openai_model.itemText(i) for i in range(self.openai_model.count())]:
            self.openai_model.setCurrentText(current_model)
        form.addRow("OpenAI Model:", self.openai_model)

        # Field indices
        self.question_idx = QLineEdit(str(self.config.get("question_field_index", 0)))
        form.addRow("Question Field Index:", self.question_idx)
        
        self.answer_idx = QLineEdit(str(self.config.get("answer_field_index", 1)))
        form.addRow("Answer Field Index:", self.answer_idx)
        
        # Advanced settings
        self.timeout = QLineEdit(str(self.config.get("timeout", 30)))
        form.addRow("Timeout (seconds):", self.timeout)
        
        self.max_retries = QLineEdit(str(self.config.get("max_retries", 3)))
        form.addRow("Max Retries:", self.max_retries)
        
        self.stream_responses = QCheckBox("Stream Responses")
        self.stream_responses.setChecked(self.config.get("stream_responses", True))
        form.addRow("", self.stream_responses)
        
        self.debug_mode = QCheckBox("Debug Mode")
        self.debug_mode.setChecked(self.config.get("debug_mode", False))
        form.addRow("", self.debug_mode)
        
        # System Prompt
        form.addRow("System Prompt:", QLabel("Edit the prompt template below:"))
        self.system_prompt = QTextEdit(self.config.get("system_prompt", ""))
        self.system_prompt.setMinimumHeight(200)
        form.addRow("", self.system_prompt)
        
        # Buttons
        buttons = QHBoxLayout()
        save_btn = QPushButton("Save")
        cancel_btn = QPushButton("Cancel")
        test_btn = QPushButton("Test Connection")
        
        qconnect(save_btn.clicked, self.save_settings)
        qconnect(cancel_btn.clicked, self.reject)
        qconnect(test_btn.clicked, self.test_connection)
        
        buttons.addWidget(save_btn)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(test_btn)

        def toggle_lm_url():
            self.lm_studio_url.setDisabled(self.use_openai.isChecked())

        self.use_openai.toggled.connect(toggle_lm_url)
        toggle_lm_url()  # initialize state

        
        # Add all to main layout
        layout.addLayout(form)
        layout.addLayout(buttons)
        self.setLayout(layout)
    
    def test_connection(self):
        """Test the connection to the LLM service"""
        try:
            if self.use_openai.isChecked():
                if not self.openai_key.text():
                    raise APIKeyError("OpenAI API key is required")
                
                response = requests.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.openai_key.text()}"
                    },
                    json={
                        "model": self.openai_model.text(),
                        "messages": [{"role": "user", "content": "test"}],
                        "max_tokens": 5
                    },
                    timeout=10
                )
                
                if response.status_code == 401:
                    raise APIKeyError("Invalid OpenAI API key")
                elif response.status_code != 200:
                    raise ConnectionError(f"OpenAI API error: {response.status_code}")
                
                showInfo("Connection successful!")
            else:
                response = requests.post(
                    self.lm_studio_url.text(),
                    headers={"Content-Type": "application/json"},
                    json={
                        "model": "local-model",
                        "messages": [{"role": "user", "content": "test"}],
                        "max_tokens": 5
                    },
                    timeout=10
                )
                
                if response.status_code != 200:
                    raise ConnectionError(f"LM Studio error: {response.status_code}")
                
                showInfo("Connection successful!")
        
        except requests.exceptions.ConnectionError:
            showCritical("Connection failed. Make sure the service is running.")
        except requests.exceptions.Timeout:
            showCritical("Connection timed out.")
        except Exception as e:
            showCritical(str(e))
        
    def save_settings(self):
        # Create a new config dictionary
        new_config = {}
        
        # Fill it with updated values
        new_config["llm_studio_url"] = self.lm_studio_url.text()
        new_config["use_openai"] = self.use_openai.isChecked()
        new_config["openai_api_key"] = self.openai_key.text()
        new_config["openai_model"] = self.openai_model.currentText()
        new_config["system_prompt"] = self.system_prompt.toPlainText()
        new_config["stream_responses"] = self.stream_responses.isChecked()
        new_config["debug_mode"] = self.debug_mode.isChecked()
        
        try:
            new_config["question_field_index"] = int(self.question_idx.text())
            new_config["answer_field_index"] = int(self.answer_idx.text())
            new_config["timeout"] = int(self.timeout.text())
            new_config["max_retries"] = int(self.max_retries.text())
        except ValueError:
            showInfo("Numeric fields must contain valid integers. Using defaults.")
            new_config["question_field_index"] = 0
            new_config["answer_field_index"] = 1
            new_config["timeout"] = 30
            new_config["max_retries"] = 3
        
        # Save the new config
        save_config(new_config)
        
        # Show confirmation
        showInfo("Configuration saved successfully!")
        self.accept()

class LLMQuizDialog(QDialog):
    def __init__(self, card, parent=None):
        super().__init__(parent)
        self.card = card
        self.note = card.note()
        self.config = get_config()
        self.is_streaming = False
        self.stream_buffer = ""
        
        try:
            # Get field indexes from config, with fallbacks
            question_idx = self.config.get("question_field_index", 0)
            answer_idx = self.config.get("answer_field_index", 1)
            
            # Make sure indexes are within range
            if question_idx >= len(self.note.fields) or answer_idx >= len(self.note.fields):
                raise ConfigurationError("Field indexes in config are out of range for this note type.")
            
            self.question = self.note.fields[question_idx]
            self.answer = self.note.fields[answer_idx]
            
            self.setWindowTitle("LLM Interactive Quiz")
            self.conversation_history = []
            self.quiz_completed = False
            
            # Setup the UI before doing anything else
            self.setup_ui()
            
            # Initialize the quiz
            self.display_question()
            
        except ConfigurationError as e:
            showCritical(str(e))
            self.reject()
        except Exception as e:
            showCritical(f"Error initializing quiz: {str(e)}")
            self.reject()

    def setup_ui(self):
        layout = QVBoxLayout()
        
        # Chat display area
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        
        # Add a clear method to make debugging easier
        self.chat_display.clear()
        
        # User input area
        self.input_field = QTextEdit()
        self.input_field.setMaximumHeight(100)
        
        # Send button
        self.send_button = QPushButton("Send Response")
        qconnect(self.send_button.clicked, self.send_message)
                
        # Add widgets to main layout
        layout.addWidget(self.chat_display)
        layout.addWidget(self.input_field)
        layout.addWidget(self.send_button)
        
        self.setLayout(layout)
        self.resize(700, 500)
        
    def display_question(self):
        """Displays the flashcard question and sets up the system prompt for the LLM."""
        self.conversation_history = []
        self.chat_display.clear()
        self.quiz_completed = False

        default_prompt = """You are an interactive flashcard tutor for Anki. Help the user learn the material effectively.

    QUESTION: {question}
    CORRECT ANSWER: {answer}

    IMPORTANT INSTRUCTIONS:
    1. NEVER repeat or restate the question - the user already sees it
    2. Wait for the user's answer
    3. Evaluate their answer as Correct, Partially Correct, or Incorrect
    4. Give specific feedback on what they got right or wrong
    5. If not fully correct, ask ONE specific guiding question
    6. Keep responses under 3 sentences
    7. Use ONLY English
    8. Focus only on the card's content - don't introduce external information

    Response Guidelines:
    - Correct answer: Acknowledge briefly. Optionally add ONE relevant detail or follow-up question
    - Partially correct: Identify what's right/wrong. Ask ONE specific question to guide them
    - Incorrect: Gently correct and ask ONE guiding question to help them learn

    NEVER start your response with "Question:", "QUESTION:", or restate the original question."""

        system_prompt_template = self.config.get("system_prompt", default_prompt)

        try:
            system_prompt = system_prompt_template.format(
                question=self.question,
                answer=self.answer
            )
        except KeyError as e:
            showInfo(f"Error formatting system prompt: Missing key {e}. Using basic prompt.")
            system_prompt = f"The user is answering: '{self.question}'. Correct answer: '{self.answer}'. Evaluate their response."

        self.conversation_history = [{"role": "system", "content": system_prompt}]

        self.chat_display.append(f"<b>Quiz:</b> Question: {self.question}")

    def send_message(self):
        user_input = self.input_field.toPlainText()
        if not user_input.strip():
            return
            
        self.chat_display.append(f"<b>You:</b> {user_input}")
        self.conversation_history.append({"role": "user", "content": user_input})
        self.input_field.clear()
        
        # Disable send button during processing
        self.send_button.setEnabled(False)
        
        threading.Thread(target=self.process_response, args=(user_input,), daemon=True).start()
    
    def process_response(self, user_input):
        """Process the LLM response with retry logic and error handling"""
        retries = 0
        max_retries = self.config.get("max_retries", 3)
        timeout = self.config.get("timeout", 30)
        
        while retries < max_retries:
            try:
                use_openai = self.config.get("use_openai", False)
                openai_key = self.config.get("openai_api_key", "")
                stream = self.config.get("stream_responses", True)
                
                if use_openai and openai_key:
                    response = requests.post(
                        "https://api.openai.com/v1/chat/completions",
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {openai_key}"
                        },
                        json={
                            "model": self.config.get("openai_model", "gpt-3.5-turbo"),
                            "messages": self.conversation_history,
                            "temperature": 0.5,
                            "max_tokens": 150,
                            "stream": stream
                        },
                        stream=stream,
                        timeout=timeout
                    )
                else:
                    response = requests.post(
                        self.config.get("llm_studio_url", "http://localhost:1234/v1/chat/completions"),
                        headers={"Content-Type": "application/json"},
                        json={
                            "model": "local-model",
                            "messages": self.conversation_history,
                            "temperature": 0.5,
                            "max_tokens": 150,
                            "stream": stream
                        },
                        stream=stream,
                        timeout=timeout
                    )
                
                if response.status_code == 401:
                    raise APIKeyError("Invalid API key")
                elif response.status_code != 200:
                    raise ConnectionError(f"API error: {response.status_code}")
                
                if stream:
                    debug_print(f"Starting streaming response with status code: {response.status_code}")
                    self.handle_stream_response(response)
                else:
                    debug_print("Using non-streaming response")
                    result = response.json()
                    llm_response = self.extract_response_text(result)
                    self.add_assistant_response(llm_response)
                
                # Re-enable send button on main thread
                mw.taskman.run_on_main(lambda: self.send_button.setEnabled(True))
                return
                
            except requests.exceptions.ConnectionError:
                retries += 1
                if retries >= max_retries:
                    mw.taskman.run_on_main(
                        lambda: self.chat_display.append("<b>Error:</b> Connection failed. Make sure the LLM service is running.")
                    )
                time.sleep(1)  # Wait before retry
                
            except requests.exceptions.Timeout:
                retries += 1
                if retries >= max_retries:
                    mw.taskman.run_on_main(
                        lambda: self.chat_display.append("<b>Error:</b> Request timed out.")
                    )
                time.sleep(1)
                
            except Exception as e:
                mw.taskman.run_on_main(
                    lambda: self.chat_display.append(f"<b>Error:</b> {str(e)}")
                )
                break
        
        # Re-enable send button on error
        mw.taskman.run_on_main(lambda: self.send_button.setEnabled(True))
    
    def handle_stream_response(self, response):
        """Handle streaming response from LLM"""
        self.is_streaming = True
        
        # Add a marker for where we'll insert the streaming text
        mw.taskman.run_on_main(
            lambda: self.chat_display.append("<b>Quiz:</b> ")
        )
        
        full_response = ""
        
        try:
            for line in response.iter_lines():
                if not line:
                    continue
                
                # Decode the line properly
                try:
                    line_str = line.decode('utf-8')
                except UnicodeDecodeError:
                    continue
                
                
                if line_str.startswith("data: "):
                    data = line_str[6:]
                    
                    try:
                        json_data = json.loads(data)
                        
                        if "choices" in json_data and json_data["choices"]:
                            delta = json_data["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                debug_print(f"Got content: {content}")
                                full_response += content
                                
                                # Append the new content
                                content_to_append = content
                                mw.taskman.run_on_main(
                                    lambda text=content_to_append: self.append_stream_text_safely(text)
                                )
                    except json.JSONDecodeError as e:
                        debug_print(f"JSON decode error: {e} - Data: {data}")
                        continue
        except Exception as e:
            debug_print(f"Streaming error: {e}")
            error_msg = str(e)
            mw.taskman.run_on_main(
                lambda msg=error_msg: self.chat_display.append(f"<b>Error:</b> Streaming failed: {msg}")
            )
        finally:
            self.is_streaming = False
            
            # Add final response to conversation history
            if full_response:
                # Clean up the response by removing <think> tags
                cleaned_response = self.clean_response_text(full_response)
                self.conversation_history.append({"role": "assistant", "content": cleaned_response})
                debug_print(f"Final response: {cleaned_response}")
            else:
                debug_print("No response received")
    
    def append_stream_text_safely(self, text):
        """Safely append text to the current position"""
        try:
            # Use simple append which is more reliable
            cursor = self.chat_display.textCursor()
            cursor.movePosition(QTextCursor.End)
            cursor.insertText(text)
            self.chat_display.setTextCursor(cursor)
            
            # Ensure visibility
            self.chat_display.ensureCursorVisible()
            
        except Exception as e:
            debug_print(f"Error appending text: {e}")
            # Fallback to simple append
            try:
                current_text = self.chat_display.toPlainText()
                self.chat_display.setText(current_text + text)
            except Exception as e2:
                debug_print(f"Fallback append failed: {e2}")
    
    def clean_response_text(self, text):
        """Remove thinking tags and clean up response text"""
        import re
        
        # Remove <think> tags and their content
        cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
        
        # Remove any standalone newlines at the start
        cleaned = cleaned.lstrip('\n')
        
        # Remove any remaining XML-like tags
        cleaned = re.sub(r'<[^>]+>', '', cleaned)
        
        return cleaned.strip()
    
    def update_placeholder_content(self, placeholder_id, content, final=False):
        """Update specific placeholder with content"""
        try:
            cursor = self.chat_display.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            
            # Move back to find our placeholder line
            found = False
            for i in range(10):  # Look back up to 10 blocks
                cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
                selected_text = cursor.selectedText()
                
                if placeholder_id in selected_text:
                    found = True
                    break
                    
                cursor.movePosition(QTextCursor.MoveOperation.Up)
            
            if found:
                # Replace the line with our content
                cursor.removeSelectedText()
                cursor.insertHtml(f"<b>Quiz:</b> {content}")
            else:
                # Fallback: append the content
                cursor.movePosition(QTextCursor.MoveOperation.End)
                cursor.insertHtml(f"<br><b>Quiz:</b> {content}")
            
            # Scroll to bottom
            self.chat_display.verticalScrollBar().setValue(
                self.chat_display.verticalScrollBar().maximum()
            )
        except Exception as e:
            debug_print(f"Error updating placeholder: {e}")
            # Fallback: just append
            self.chat_display.append(f"<b>Quiz:</b> {content}")
    
    def remove_placeholder(self, placeholder_id):
        """Remove a specific placeholder"""
        html = self.chat_display.toHtml()
        placeholder = f'<span id="{placeholder_id}"></span>'
        
        if placeholder in html:
            new_html = html.replace(f"<b>Quiz:</b> {placeholder}", "")
            self.chat_display.setHtml(new_html)
    
    def update_stream_display_with_content(self, content):
        """Update the display with specific content"""
        cursor = self.chat_display.textCursor()
        cursor.movePosition(cursor.End)
        
        # Find the streaming span
        cursor.movePosition(cursor.StartOfBlock)
        cursor.movePosition(cursor.EndOfBlock, cursor.KeepAnchor)
        
        selected_text = cursor.selectedText()
        if "<span id='streaming'>" in selected_text or selected_text.startswith("Quiz:"):
            # Replace the whole line with the updated content
            cursor.insertHtml(f"<b>Quiz:</b> {content}")
            
        # Scroll to bottom
        self.chat_display.verticalScrollBar().setValue(
            self.chat_display.verticalScrollBar().maximum()
        )
    
    def finalize_streamed_response(self, final_content):
        """Finalize the streamed response display"""
        cursor = self.chat_display.textCursor()
        cursor.movePosition(cursor.End)
        
        # Go to the last quiz response
        cursor.movePosition(cursor.StartOfBlock)
        cursor.movePosition(cursor.EndOfBlock, cursor.KeepAnchor)
        
        # Replace with the final content
        cursor.insertHtml(f"<b>Quiz:</b> {final_content}")
        
        # Scroll to bottom
        self.chat_display.verticalScrollBar().setValue(
            self.chat_display.verticalScrollBar().maximum()
        )
    
    def update_stream_display(self):
        """Update the display with streamed content"""
        # This method is now deprecated in favor of update_stream_display_with_content
        pass
    
    def add_assistant_response(self, response):
        """Add assistant response to chat display"""
        # Clean the response first
        cleaned_response = self.clean_response_text(response)
        
        # Filter out any responses that still try to repeat the question
        if cleaned_response.lower().startswith("question:") or self.question.lower() in cleaned_response.lower()[:30]:
            # Skip the question part if the LLM included it
            lines = cleaned_response.split('\n')
            cleaned_response = '\n'.join([line for line in lines if not line.lower().startswith("question:")])
        
        if cleaned_response.strip():
            self.conversation_history.append({"role": "assistant", "content": cleaned_response})
            mw.taskman.run_on_main(
                lambda: self.chat_display.append(f"<b>Quiz:</b> {cleaned_response}")
            )
    
    def extract_response_text(self, response):
        # Handle different API response formats
        if "choices" in response and response["choices"]:
            if "message" in response["choices"][0]:
                return response["choices"][0]["message"]["content"]
            elif "text" in response["choices"][0]:
                return response["choices"][0]["text"]
        return "Error: Unexpected response format from LLM service."

    def rate_card(self, ease):
        """Rate the card and close the dialog"""
        try:
            # First try the newer method in Anki 24.11+
            mw.reviewer._answeredCard(self.card, ease)
        except (AttributeError, TypeError):
            try:
                # Try the older method for earlier Anki versions
                mw.reviewer.answerCard(self.card, ease)
            except (AttributeError, TypeError):
                # Fall back to a very basic approach
                showInfo("Could not automatically rate the card. Please rate it manually.")
        
        self.accept()  # Close dialog

# Create a button to launch the LLM quiz
def on_llm_quiz():
    card = mw.reviewer.card
    if not card:
        showInfo("No card is currently being reviewed.")
        return
        
    dialog = LLMQuizDialog(card, mw)
    # Use exec() instead of exec_() for Anki 24.11
    dialog.exec()

def on_config():
    dialog = ConfigDialog(mw)
    dialog.exec()

# Add menu items
llm_quiz_action = QAction("LLM Interactive Quiz", mw)
qconnect(llm_quiz_action.triggered, on_llm_quiz)
mw.form.menuTools.addAction(llm_quiz_action)

config_action = QAction("Configure LLM Quiz", mw)
qconnect(config_action.triggered, on_config)
mw.form.menuTools.addAction(config_action)

# Register the config action with Anki
mw.addonManager.setConfigAction(__name__, on_config)

# Add a hook to show a button on both the question and answer sides of the card
def add_llm_button(html, card, kind):
    """Add an LLM Quiz button to both the question and answer sides of the card"""
    if kind == "reviewQuestion" or kind == "reviewAnswer":
        position = "text-align: right;" if kind == "reviewQuestion" else "text-align: center; margin-top: 20px;"
        button = f"""
        <div style="{position}">
            <button id="llm-quiz-btn" onclick="pycmd('llm_quiz');" style="
                background-color: #4CAF50;
                border: none;
                color: white;
                padding: 10px 20px;
                text-align: center;
                text-decoration: none;
                display: inline-block;
                font-size: 16px;
                margin: 10px 2px;
                cursor: pointer;
                border-radius: 5px;">
                Study with LLM
            </button>
        </div>
        """
        return html + button
    return html

card_will_show.append(add_llm_button)

# Handle the button click
def handle_llm_quiz_button(handled, message, context):
    if message == "llm_quiz":
        on_llm_quiz()
        return (True, None)  # Return a tuple instead of just True
    return handled

webview_did_receive_js_message.append(handle_llm_quiz_button)