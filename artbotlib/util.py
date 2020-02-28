import datetime
from fcntl import fcntl, F_GETFL, F_SETFL
import logging
import os
import shlex
import subprocess
import time


logger = logging.getLogger()


def please_notify_art_team_of_error(so, payload):
    dt = datetime.datetime.today().strftime('%Y-%m-%d-%H-%M-%S')
    so.snippet(payload=payload,
               intro='Sorry, I encountered an error. Please contact @art-team with the following details.',
               filename=f'error-details-{dt}.txt')


def cmd_gather(cmd, set_env=None, cwd=None, realtime=False):
    """
    Runs a command and returns rc,stdout,stderr as a tuple.

    If called while the `Dir` context manager is in effect, guarantees that the
    process is executed in that directory, even if it is no longer the current
    directory of the process (i.e. it is thread-safe).

    :param cmd: The command and arguments to execute
    :param cwd: The directory from which to run the command
    :param set_env: Dict of env vars to set for command (overriding existing)
    :param realtime: If True, output stdout and stderr in realtime instead of all at once.
    :return: (rc,stdout,stderr)
    """

    if not isinstance(cmd, list):
        cmd_list = shlex.split(cmd)
    else:
        cmd_list = cmd

    cmd_info = '[cwd={}]: {}'.format(cwd, cmd_list)

    env = os.environ.copy()
    if set_env:
        cmd_info = '[env={}] {}'.format(set_env, cmd_info)
        env.update(set_env)

    # Make sure output of launched commands is utf-8
    env['LC_ALL'] = 'en_US.UTF-8'

    logger.debug("Executing:cmd_gather {}".format(cmd_info))
    try:
        proc = subprocess.Popen(
            cmd_list, cwd=cwd, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        logger.error("Subprocess errored running:\n{}\nWith error:\n{}\nIs {} installed?".format(
            cmd_info, exc, cmd_list[0]
        ))
        return exc.errno, "", "Subprocess errored running:\n{}\nWith error:\n{}\nIs {} installed?".format(
            cmd_info, exc, cmd_list[0]
        )

    if not realtime:
        out, err = proc.communicate()
        rc = proc.returncode
    else:
        out = b''
        err = b''

        # Many thanks to http://eyalarubas.com/python-subproc-nonblock.html
        # setup non-blocking read
        # set the O_NONBLOCK flag of proc.stdout file descriptor:
        flags = fcntl(proc.stdout, F_GETFL)  # get current proc.stdout flags
        fcntl(proc.stdout, F_SETFL, flags | O_NONBLOCK)
        # set the O_NONBLOCK flag of proc.stderr file descriptor:
        flags = fcntl(proc.stderr, F_GETFL)  # get current proc.stderr flags
        fcntl(proc.stderr, F_SETFL, flags | O_NONBLOCK)

        rc = None
        while rc is None:
            output = None
            try:
                output = read(proc.stdout.fileno(), 256)
                logger.info(f'{cmd_info} stdout: {out.rstrip()}')
                out += output
            except OSError:
                pass

            error = None
            try:
                error = read(proc.stderr.fileno(), 256)
                logger.warning(f'{cmd_info} stderr: {error.rstrip()}')
                out += error
            except OSError:
                pass

            rc = proc.poll()
            time.sleep(0.0001)  # reduce busy-wait

    # We read in bytes representing utf-8 output; decode so that python recognizes them as unicode strings
    out = out.decode('utf-8')
    err = err.decode('utf-8')
    logger.debug(
        "Process {}: exited with: {}\nstdout>>{}<<\nstderr>>{}<<\n".
        format(cmd_info, rc, out, err))
    return rc, out, err





def cmd_assert(so, cmd, set_env=None, cwd=None, realtime=False):
    """
    A cmd_gather invocation, but if it fails, it will notify the
    alert the monitoring channel and the requesting user with
    information about the failure.
    :return:
    """

    error_id = f'{so.from_user_id()}.{int(time.time()*1000)}'

    def send_cmd_error(rc, stdout, stderr):
        intro = f'Error running command (for user={so.from_user_mention()} error-id={error_id}): {cmd}'
        payload = f"rc={rc}\n\nstdout={stdout}\n\nstderr={stderr}\n"
        so.monitoring_snippet(intro=intro, filename='cmd_error.log', payload=payload)

    try:
        rc, stdout, stderr = cmd_gather(cmd, set_env, cwd, realtime)
    except subprocess.CalledProcessError as exec:
        send_cmd_error(exec.returncode, exec.stdout, exec.stderr)
        raise
    except:
        send_cmd_error(-1000, '', traceback.format_exc())
        raise

    if rc:
        logger.warning(f'error-id={error_id} . Non-zero return code from: {cmd}\nStdout:\n{stdout}\n\nStderr:\n{stderr}\n')
        send_cmd_error(rc, stdout, stderr)
        so.say(f'Sorry, but I encountered an error. Details have been sent to the ART team. Mention error-id={error_id} when requesting support.')
        raise IOError(f'Non-zero return code from: {cmd}')

    return rc, stdout, stderr
