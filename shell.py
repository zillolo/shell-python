import curses
from curses import cbreak, echo, endwin, initscr, nocbreak, noecho
import logging
from os import chdir, environ, getcwd
from subprocess import check_output, CalledProcessError, Popen, PIPE
from time import sleep
from threading import Thread
from queue import Queue


class History:

    def __init__(self):
        self.__commands = []
        self.__selectedIndex = 0

    def add(self, command):
        self.__commands.append(command)
        self.__selectedIndex = len(self.__commands)

    def previous(self):
        if self.__selectedIndex - 1 >= 0:
            self.__selectedIndex -= 1
            return self.__commands[self.__selectedIndex]
        return None

    def next(self):
        if self.__selectedIndex + 1 < len(self.__commands):
            self.__selectedIndex += 1
            return self.__commands[self.__selectedIndex]
        return None

    def last(self):
        if len(self.__commands) != 0:
            return self.__commands[-1]
        return None


class ExitCalledException(Exception):
    pass


class Shell:

    def __init__(self):
        self.__initEnvironment()
        self.__initConfig()
        self.__initHistory()
        self.__initLogging()
        self.__initWindow()

        self.__jobs = []

        logging.info("Starting writer...")
        self.writer = Shell.Writer(self.__window)
        self.writer.start()

    def __initConfig(self):
        self.__config = {}

        self.__resetPrompt()

    def __initEnvironment(self):
        self.__environment = {}

        self.__environment["HOME"] = environ.get("HOME")
        self.__environment["PWD"] = environ.get("PWD")

    def __initHistory(self):
        self.history = History()

    def __initLogging(self):
        with open("debug.log", "w"):
            pass

        logging.basicConfig(filename="debug.log",
                            level=logging.DEBUG)

    def __resetPrompt(self):
        prompt = "{0} $".format(self.__environment["PWD"])
        self.__config["PROMPT"] = prompt.replace(
            self.__environment["HOME"], "~")

    def __initWindow(self):
        self.__window = initscr()
        noecho()
        cbreak()
        self.__window.keypad(True)
        self.__window.scrollok(True)
        self.__window.idlok(1)

    def __deinitWriter(self):
        logging.info("Stopping writer...")
        self.writer.stop()
        self.writer.join()

    def __deinitWindow(self):
        logging.info("Destructing window...")
        nocbreak()
        self.__window.keypad(False)
        echo()
        endwin()

    def run(self):
        try:
            while True:
                self.writer.add("\r{0}".format(self.__config["PROMPT"]))
                self.__fetch()
                self.__execute()
        except Exception as e:
            logging.info(e)
        finally:
            self.__deinitWriter()
            self.__deinitWindow()
            logging.info("Application closing.")

    def __fetch(self):
        command = ""

        while True:
            # FIXME: KeyboardInterrupt results in chr() arg out of range?
            try:
                character = self.__window.getch()

                if character == curses.KEY_ENTER or character == 10:
                    if len(command.strip()) != 0:
                        command += "\n"
                        break
                    else:
                        self.writer.add("\n")
                elif character == curses.KEY_BACKSPACE:
                    command = command[0:-1]
                elif character == curses.KEY_UP:
                    temp = self.history.previous()
                    if temp is not None:
                        command = temp
                elif character == curses.KEY_DOWN:
                    temp = self.history.next()
                    if temp is not None:
                        command = temp
                else:
                    command += chr(character)
                self.writer.add("\r{0}{1}".format(
                    self.__config["PROMPT"], command))
            except KeyboardInterrupt:
                pass
        self.writer.add("\n")
        self.history.add(command.strip())

    def __execute(self):
        command = self.history.last().split()
        command = self.__replaceEnvironmentVars(command)
        logging.info("Executing: {0}".format(command))

        if command[0] == "exit":
            self.__exit()
        elif command[0] == "cd":
            if len(command) == 2:
                self.__changeDir(command[1])
            else:
                self.writer.add("cd: Need directory as argument.\n")
        else:
            try:
                pipe = Popen(command, stdout=PIPE)
                output = pipe.communicate()[0]
                self.writer.add(output.decode("utf-8"))
            except FileNotFoundError:
                self.writer.add(
                    "Command not found: {0}\n".format(command[0]))
            except KeyboardInterrupt:
                pass

    def __replaceEnvironmentVars(self, command):
        for i, t in enumerate(command):
            if t.startswith("$"):
                logging.info("Found env variable.")
                value = self.__environment.get(t[1:len(t)])
                logging.info("Value: {0}".format(value))
                if value != None:
                    logging.info("Replaced {0} with {1}.".format(t, value))
                    command[i] = value
        return command

    def __exit(self):
        raise ExitCalledException("Exit called by user.")

    def __changeDir(self, path):
        try:
            path = path.replace("~", self.__environment["HOME"])
            chdir(path)
            self.__environment["PWD"] = getcwd()
            self.__resetPrompt()
        except OSError:
            self.writer.add(
                "cd: Invalid path. Did not change directory.\n")

    class Writer(Thread):

        class Cursor:

            def __init__(self, x=0, y=0):
                self.x = x
                self.y = y

            def move(self, x, y):
                self.x = x
                self.y = y

            def reset(self):
                self.x = 0

            def left(self):
                self.x -= 1

            def right(self):
                self.x += 1

            def up(self):
                self.y -= 1

            def down(self):
                self.y += 1

        def __init__(self, window):
            super(Shell.Writer, self).__init__()
            self.__cursor = Shell.Writer.Cursor(0, 0)
            self.__stopCalled = False

            self.__queue = Queue()
            self.__window = window

        def add(self, message):
            if message is not None:
                self.__queue.put(message)

        def run(self):
            while not self.__stopCalled:
                if not self.__queue.empty():
                    message = self.__queue.get()
                    self.__print(message)
                    self.__window.move(self.__cursor.y, self.__cursor.x)
                    self.__window.refresh()
            sleep(0.1)

        def stop(self):
            self.__stopCalled = True

        def __print(self, message):
            height, _ = self.__window.getmaxyx()
            for character in message:
                if character == "\n":
                    self.__cursor.reset()
                    if self.__cursor.y + 1 >= height:
                        self.__window.scroll(1)
                    else:
                        self.__cursor.down()
                elif character == "\r":
                    self.__cursor.reset()
                    self.__window.move(self.__cursor.y, self.__cursor.x)
                    self.__window.clrtoeol()
                else:
                    self.__window.addch(
                        self.__cursor.y, self.__cursor.x, character)
                    self.__cursor.right()

if __name__ == "__main__":
    sh = Shell()
    sh.run()
