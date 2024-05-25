import io
import re
import openai
import os
import sys
import ollama
import yaml
from pynput.keyboard import Controller
import textwrap
import psutil
import platform
import shutil
import time
import pyautogui
from dotenv import load_dotenv

# =============================================================================
# CONFIGURATION
# =============================================================================

# Set up OpenAI API
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

# Define the keyboard controller
kbd = Controller()

# Define ANSI colors
yellow = "\033[93m"
dark_green = "\033[32m"
reset = "\033[0m"
color_comment = dark_green
color_command = yellow

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def get_system_info():
    os_name = os.name
    platform_system = platform.system()
    platform_release = platform.release()
    platform_version = platform.version()
    platform_machine = platform.machine()
    platform_processor = platform.processor()
    platform_wsl = os.environ.get('WSL_DISTRO_NAME') is not None

    return f"operating system: {os_name}\n" + \
        f"platform: {platform_system}\n" + \
        f"release: {platform_release}\n" + \
        f"version: {platform_version}\n" + \
        f"machine: {platform_machine}\n" + \
        f"processor: {platform_processor}\n" + \
        f"wsl: {'yes' if platform_wsl else 'no'}"


def get_shell():
    # return first non python parent process, and remove .exe
    for process in psutil.Process(os.getppid()).parents():
        if "python" not in process.name().lower():
            return process.name().lower().replace(".exe", "")


def get_shell_version(shell):
    if shell == "powershell":
        return os.popen("powershell -Command $PSVersionTable.PSVersion").read()
    elif shell == "bash":
        return os.popen(f"{shell} --version").read().splitlines()[0]
    else:
        return os.popen(f"{shell} --version").read()


def get_working_directory():
    return os.getcwd()


def get_last_commands():
    return os.popen('history').read()


def get_package_managers():
    package_managers = [
        "pip",
        "conda",
        "npm",
        "yarn",
        "gem",
        "apt",
        "dnf",
        "yum",
        "pacman",
        "zypper",
        "brew",
        "choco",
        "scoop",
    ]

    installed_package_managers = []

    for pm in package_managers:
        if shutil.which(pm):
            installed_package_managers.append(pm)

    return installed_package_managers


def sudo_available():
    return shutil.which("sudo") is not None

# =============================================================================
# CHATGPT FUNCTIONS
# =============================================================================


def generate_chat_gpt_messages(user_input):
    shell = get_shell()
    shell_version = get_shell_version(shell)
    system_info = get_system_info()
    working_directory = get_working_directory()
    package_managers = get_package_managers()
    sudo = sudo_available()

    # open prompts relative to this file
    prompts = yaml.load(
        open(os.path.join(os.path.dirname(__file__), "prompts.yaml"), "r"),
        Loader=yaml.FullLoader
    )

    shell_messages = prompts['bash']['messages']
    if shell == "powershell":
        shell_messages = prompts['powershell']['messages']

    common_messages = prompts['common']['messages']

    # replace parameters in each message content
    for message in common_messages:
        message['content'] = message['content'].format(
            shell=shell,
            shell_version=shell_version,
            system_info=system_info,
            working_directory=working_directory,
            package_managers=', '.join(package_managers),
            sudo='sudo' if sudo else 'no sudo',
        )
    user_message = {
        "role": "user",
        "content": user_input,
    }
    return common_messages + shell_messages + [user_message]


# def get_bash_command(messages):
#     response = openai.ChatCompletion.create(
#         model="gpt-4",
#         messages=messages,
#         max_tokens=1000,
#         n=1,
#         stop=None,
#         temperature=0.7,
#         request_timeout=30
#     )

#     bash_command = response['choices'][0]['message']['content'].strip()
#     return bash_command

# =============================================================================
# OLLAMA FUNCTION
# =============================================================================
def chat(messages, model='llama3'):
    try:
        # print("Sending the following messages to Ollama API:")
        for message in messages:
            print(message)
        response = ollama.chat(model=model, messages=messages)
        # print("Received response from Ollama API:", response)
        
        # Ensure the response is in the expected format
        if isinstance(response, dict) and 'message' in response and 'content' in response['message']:
            return response['message']['content']
        else:
            raise ValueError("Unexpected response format")
    except Exception as e:
        print(f"An error occurred: {e}")
        error_message = str(e).lower()
        if "not found" in error_message:
            return f"Model '{model}' not found. Please refer to Documentation at https://ollama.com/library."
        else:
            return f"An unexpected error occurred with model '{model}': {str(e)}"

# =============================================================================
# MAIN FUNCTION
# =============================================================================


def main():
    if len(sys.argv) != 2:
        print("Usage: python ai.py \"<natural language command>\"")
        sys.exit(1)

    user_input = sys.argv[1]

    options = []

    # remove flags from the start of the input and add them to the options list
    while user_input.startswith('-'):
        option, user_input = user_input.split(' ', 1)
        options.append(option)
    # Prepend stdin to the user input, if present
    if sys.stdin.isatty():
        pass
    else:
        stdin = sys.stdin.read().strip()
        if len(stdin):
            user_input = f"{user_input}. Use the following additional context to improve your suggestion:\n\n---\n\n{stdin}\n"

    os.system('')
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf8')
    messages = generate_chat_gpt_messages(user_input)

    if '--debug' in options:
        # print the role and content of each message if debugging
        for message in messages:
            print(
                f"{color_comment}{message['role']}: {message['content']}{reset}")
        sys.exit(0)

    print(f"{color_comment}🤖 Thinking ...{reset}", end='')
    sys.stdout.flush()
    bash_command = chat(messages)  # swappy swappy
    # Overwrite the "thinking" message
    print(f"\r{' ' * 80}\r", end='')
    os.system('')
    print('🤖')

    # Get all lines that are not comments
    def normalize_command(command):
        return re.sub(r'\s*&& \\\s*$', '', command.strip(';').strip())

    def get_executable_commands(command):
        commands = []
        for command in bash_command.splitlines():
            if command.startswith('#'):
                continue
            normalized_command = normalize_command(command)

            if len(normalized_command) > 0:
                commands.append(normalized_command)
        return commands

    executable_commands = get_executable_commands(bash_command)

    for line in bash_command.splitlines():
        if len(line.strip()) == 0:
            continue

        # Print out any comments in yellow
        if line.startswith('#'):
            comment = textwrap.fill(
                line, width=80, initial_indent='  ', subsequent_indent='  ')
            print(f"{color_comment}{comment}{reset}")
        # Print out the executable command in yellow, if there are multiple commands
        elif len(line) and len(executable_commands) > 1:
            print(f"  {color_command}{line}{reset}\n")

    sys.stdout.flush()

    type_commands(executable_commands)


def type_commands(executable_commands):
    # powershell
    if get_shell() == 'powershell':
        # if its a single command, just type it
        if len(executable_commands) == 1:
            pyautogui.typewrite(executable_commands[0])
            return

        # Wrap everything in the Do alias
        pyautogui.typewrite("AiDo {\n")
        for command_index, command in enumerate(executable_commands):
            pyautogui.typewrite(command)
            pyautogui.typewrite("\n")
        pyautogui.typewrite("}")
    else:
        for command_index, command in enumerate(executable_commands):
            pyautogui.typewrite(command)
            if command_index < len(executable_commands) - 1 and not command.endswith('\\'):
                pyautogui.typewrite(" && \\\n")


if __name__ == "__main__":
    main()
