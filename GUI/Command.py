import os
import logging

from PySide6.QtCore import QObject, QRunnable, Slot, Signal

from GUI.ProjectDataModel import ProjectDataModel
from GUI.ViewModel.ViewModelUpdate import ModelUpdate
from PySubtitle.SubtitleError import TranslationAbortedError, TranslationImpossibleError

if os.environ.get("DEBUG_MODE") == "1":
    try:
        import debugpy # type: ignore
    except ImportError:
        logging.warning("debugpy is not available, breakpoints on worker threads will not work")

class Command(QRunnable, QObject):
    commandExecuted = Signal(object, bool)

    def __init__(self, datamodel : ProjectDataModel = None):
        QRunnable.__init__(self)
        QObject.__init__(self)
        self.datamodel = datamodel
        self.can_undo : bool = True         # Cannot undo past this command
        self.skip_undo : bool = False       # Do not add this command to the undo stack
        self.is_blocking : bool = True      # Do not execute any other commands in parallel
        self.started : bool = False
        self.executed : bool = False
        self.aborted : bool = False
        self.terminal : bool = False        # Command ended with a fatal error, no further commands can be executed
        self.callback = None
        self.undo_callback = None
        self.model_updates : list[ModelUpdate] = []
        self.commands_to_queue : list[Command] = []

    def SetDataModel(self, datamodel):
        self.datamodel = datamodel

    def SetCallback(self, callback):
        self.callback = callback

    def SetUndoCallback(self, undo_callback):
        self.undo_callback = undo_callback

    def Abort(self):
        if not self.aborted:
            self.aborted = True
            self.on_abort()

    def AddModelUpdate(self) -> ModelUpdate:
        update = ModelUpdate()
        self.model_updates.append(update)
        return update

    def ClearModelUpdates(self):
        self.model_updates = []

    @Slot()
    def run(self):
        if self.aborted:
            logging.debug(f"Aborted {type(self).__name__} before it started")
            self.commandExecuted.emit(self, False)
            return

        if 'debugpy' in globals():
            debugpy.debug_this_thread()

        try:
            success = self.execute()

            if self.aborted:
                logging.info(f"Aborted {type(self).__name__}")
                success = False

            elif self.terminal:
                logging.error(f"Unrecoverable error in {type(self).__name__}")
                success = False

            self.commandExecuted.emit(self, success)

        except Exception as e:
            logging.error(f"Error executing {type(self).__name__}: ({str(e)})")
            self.commandExecuted.emit(self, False)

    def execute(self):
        raise NotImplementedError

    def undo(self):
        if self.skip_undo:
            logging.warning(f"Command {type(self).__name__} has no undo function and is not set to skip undo")
            return False

        raise NotImplementedError

    def on_abort(self):
        pass

    def execute_callback(self):
        if self.callback:
            self.callback(self)

    def execute_undo_callback(self):
        if self.undo_callback:
            self.undo_callback(self)

class CommandError(Exception):
    def __init__(self, command : Command, *args: object) -> None:
        super().__init__(*args)
        self.command = command

class UndoError(CommandError):
    pass

