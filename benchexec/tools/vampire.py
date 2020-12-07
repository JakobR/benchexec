# This file is part of BenchExec, a framework for reliable benchmarking:
# https://github.com/sosy-lab/benchexec
#
# SPDX-FileCopyrightText: 2007-2020 Dirk Beyer <https://www.sosy-lab.org>
#
# SPDX-License-Identifier: Apache-2.0

import benchexec
import benchexec.result as result


class Tool(benchexec.tools.template.BaseTool2):
    """
    Tool info for Vampire.
    https://github.com/vprover/vampire
    """

    def name(self):
        return "Vampire"

    def executable(self, tool_locator):
        return tool_locator.find_executable("vampire")

    def version(self, executable):
        line = self._version_from_tool(executable, line_prefix="Vampire")
        line = line.strip()
        line = line.split(" ")[0]
        return line.strip()

    def environment(self, executable):
        """
        OPTIONAL, this method is only necessary for tools
        that needs special environment variable, such as a modified PATH.
        However, for usability of the tool it is in general not recommended to require
        additional variables (tool uses outside of BenchExec would need to have them specified
        manually), but instead change the tool such that it does not need additional variables.
        For example, instead of requiring the tool directory to be added to PATH,
        the tool can be changed to call binaries from its own directory directly.
        This also has the benefit of not confusing bundled binaries
        with existing binaries of the system.

        Note that when executing benchmarks under a separate user account (with flag --user),
        the environment of the tool is a fresh almost-empty one.
        This function can be used to set some variables.

        Note that runexec usually overrides the environment variable $HOME and sets it to a fresh
        directory. If your tool relies on $HOME pointing to the real home directory,
        you can use the result of this function to overwrite the value specified by runexec.
        This is not recommended, however, because it means that runs may be influenced
        by files in the home directory, which hinders reproducibility.

        This method returns a dict that contains several further dicts.
        All keys and values have to be strings.
        Currently we support 3 identifiers in the outer dict:

        "keepEnv": If specified, the run gets initialized with a fresh environment and only
                  variables listed in this dict are copied from the system environment
                  (the values in this dict are ignored).
        "newEnv": Before the execution, the values are assigned to the real environment-identifiers.
                  This will override existing values.
        "additionalEnv": Before the execution, the values are appended to the real environment-identifiers.
                  The seperator for the appending must be given in this method,
                  so that the operation "realValue + additionalValue" is a valid value.
                  For example in the PATH-variable the additionalValue starts with a ":".
        @param executable: the path to the executable of the tool (typically the result of executable())
        @return a possibly empty dict with three possibly empty dicts with environment variables in them
        """
        return {"keepEnv": {"TPTP": 1}}

    # Methods for handling individual runs and their results

    def cmdline(self, executable, options, task, rlimits):
        """
        Compose the command line to execute from the name of the executable,
        the user-specified options, and the inputfile to analyze.
        This method can get overridden, if, for example, some options should
        be enabled or if the order of arguments must be changed.

        All paths passed to this method (executable and fields of task)
        are either absolute or have been made relative to the designated working directory.

        @param executable: the path to the executable of the tool (typically the result of executable())
        @param options: a list of options, in the same order as given in the XML-file.
        @param task: An instance of of class Task, e.g., with the input files
        @param rlimits: An instance of class ResourceLimits with the limits for this run
        @return a list of strings that represent the command line to execute
        """
        assert len(task.input_files) <= 1, "only one input file supported"

        if "-t" not in options and "--time_limit" not in options:
            if rlimits.walltime is None:
                # Default timeout of Vampire is 60s,
                # so we set value of 0 explicitly (means unlimited)
                options += ["-t", "0"]
            else:
                options += ["-t", f"{rlimits.walltime}s"]

        if "-m" not in options and "--memory_limit" not in options:
            if rlimits.memory is None:
                # No memory limit has been set
                # TODO: should we warn in this case? Vampire is going to use the default of 3000MB
                pass
            else:
                # Vampire's option '--memory_limit/-m' takes the value in MiB
                memory_mb = int(rlimits.memory / (1024 * 1024))
                options += ["-m", f"{memory_mb}"]

        # print(f"Running vampire with: {[executable, *options, *task.input_files]}")
        return [executable, *options, *task.input_files]

    def determine_result(self, run):
        """
        Parse the output of the tool and extract the verification result.
        If the tool gave a result, this method needs to return one of the
        benchexec.result.RESULT_* strings.
        Otherwise an arbitrary string can be returned that will be shown to the user
        and should give some indication of the failure reason
        (e.g., "CRASH", "OUT_OF_MEMORY", etc.).
        For tools that do not output some true/false result, benchexec.result.RESULT_DONE
        can be returned (this is also the default implementation).
        BenchExec will then automatically add some more information
        if the tool was killed due to a timeout, segmentation fault, etc.
        @param run: information about the run as instanceof of class Run
        @return a non-empty string, usually one of the benchexec.result.RESULT_* constants
        """
        status = self.get_szs_status(run.output)
        # print("")
        # print(f"SZS status: {status}")
        # print(f"Termination reasons: {self.get_other_termination_reasons(run.output)}")
        # print(f"Exit code: {run.exit_code}")
        # print(f"Terminated by benchexec? {run.termination_reason}")
        if run.exit_code:
            if status == "Timeout":
                return "TIMEOUT"
            if run.exit_code.value == 4:
                # Some kind of system error happened
                if run.output.text.startswith("Parsing error"):
                    return "Parsing error"
            if run.exit_code.value == 1:
                # Not really an error but unable to finish
                reasons = self.get_other_termination_reasons(run.output)
                if reasons == ["Time limit"]:
                    return "TIMEOUT"
                if reasons == ["Refutation not found, incomplete strategy"]:
                    return "Incomplete"
                if reasons == ["Refutation not found, non-redundant clauses discarded"]:
                    return "Incomplete"
            # Some other error
            return result.RESULT_ERROR
        else:
            # Successfully finished
            if status in self.SZS_UNSAT:
                return result.RESULT_TRUE_PROP
            elif status in self.SZS_SAT:
                return result.RESULT_FALSE_PROP
            else:
                return result.RESULT_UNKNOWN

    # SZS status values that Vampire returns
    SZS_UNSAT = ["ContradictoryAxioms", "Theorem", "Unsatisfiable"]
    SZS_SAT = ["CounterSatisfiable", "Satisfiable"]
    SZS_FAIL = ["Timeout", "GaveUp", "User"]

    def get_szs_status(self, output):
        """
        Extract the SZS status from the output.
        @param output: The output of the tool as instance of class RunOutput.
        @return a non-empty string, or None if no unique SZS status was found
        """
        status = None
        for line in output:
            if line.startswith("% SZS status"):
                if status is None:
                    words = line.split()
                    status = words[3] if len(words) >= 4 else None
                else:
                    # More than one SZS status => this is an error!
                    return None
        return status

    def get_other_termination_reasons(self, output):
        """
        Extract termination reasons from the output from lines starting with '% Termination reason'.
        @param output: The output of the tool as instance of class RunOutput.
        @return List of strings, the termination found in the output (without prefix).
        """
        prefix = "% Termination reason: "
        reasons = []
        for line in output:
            if line.startswith(prefix):
                reasons.append(line[len(prefix) :])
        return reasons

    def get_value_from_output(self, output, identifier):
        """
        OPTIONAL, extract a statistic value from the output of the tool.
        This value will be added to the resulting tables.
        It may contain HTML code, which will be rendered appropriately in the HTML tables.

        Note that this method may be called without any of the other methods called
        before it and without any existing installation of the tool on this machine
        (because table-generator uses this method).

        @param output: The output of the tool as instance of class RunOutput.
        @param identifier: The user-specified identifier for the statistic item.
        @return a (possibly empty) string, optional with HTML tags
        """
        # TODO
        # Extract SZS result and stats, runtimestats, time stats?
        # Only for single-strategy runs.
        # For portfolio, return 'successful_strategy'?
        print(f"get_value for id {identifier}")
        if identifier == "szs-status":
            return self.get_szs_status(output) or "--"
