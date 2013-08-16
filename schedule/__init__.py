"""
Python job scheduling for humans.

An in-process scheduler for periodic jobs that uses the builder pattern
for configuration. Schedule lets you run Python functions (or any other
callable) periodically at pre-determined intervals using a simple,
human-friendly syntax.

Inspired by Addam Wiggins' article "Rethinking Cron" [1] and the
"clockwork" Ruby module [2][3].

Features:
    - A simple to use API for scheduling jobs.
    - Very lightweight and no external dependencies.
    - Excellent test coverage.
    - Works with Python 2.7 and 3.3

Usage:
    >>> import schedule
    >>> import time

    >>> def job(message='stuff'):
    >>>     print("I'm working on:", message)

    >>> schedule.every(10).minutes.do(job)
    >>> schedule.every().hour.do(job, message='things')
    >>> schedule.every().day.at("10:30").do(job)

    >>> while True:
    >>>     schedule.run_pending()
    >>>     time.sleep(1)

[1] http://adam.heroku.com/past/2010/4/13/rethinking_cron/
[2] https://github.com/tomykaira/clockwork
[3] http://adam.heroku.com/past/2010/6/30/replace_cron_with_clockwork/
"""
import datetime
import functools
import logging
import random
import time

logger = logging.getLogger('schedule')


class Scheduler(object):
    def __init__(self):
        self.jobs = []

    def run_pending(self):
        """Run all jobs that are scheduled to run.

        Please note that it is *intended behavior that tick() does not
        run missed jobs*. For example, if you've registered a job that
        should run every minute and you only call tick() in one hour
        increments then your job won't be run 60 times in between but
        only once.
        """
        runnable_jobs = (job for job in self.jobs if job.should_run)
        for job in sorted(runnable_jobs):
            job.run()

    def run_all(self, delay_seconds=0):
        """Run all jobs regardless if they are scheduled to run or not.

        A delay of `delay` seconds is added between each job. This helps
        distribute system load generated by the jobs more evenly
        over time."""
        logger.info('Running *all* %i jobs with %is delay inbetween',
                    len(self.jobs), delay_seconds)
        for job in self.jobs:
            job.run()
            time.sleep(delay_seconds)

    def clear(self):
        """Deletes all scheduled jobs."""
        del self.jobs[:]

    def every(self, interval=1):
        """Schedule a new periodic job."""
        job = Job(interval)
        self.jobs.append(job)
        return job

    def on(self, *days):
        """Schedule a new job to run on specific weekdays.

        See the docstring for `Job.on()`.
        """
        job = self.every()
        job.unit = 'days'
        return job.on(*days)

    @property
    def next_run(self):
        """Datetime when the next job should run."""
        if not self.jobs:
            return None
        return min(self.jobs).next_run

    @property
    def idle_seconds(self):
        """Number of seconds until `next_run`."""
        return (self.next_run - datetime.datetime.now()).total_seconds()


class Job(object):
    """A periodic job as used by `Scheduler`."""
    WEEKDAYS = {'sunday': 0, 'monday': 1, 'tuesday': 2, 'wednesday': 3,
                'thursday': 4, 'friday': 5, 'saturday': 6}

    def __init__(self, interval):
        self.interval = interval  # pause interval * unit between runs
        self.job_func = None  # the job job_func to run
        self.unit = None  # time units, e.g. 'minutes', 'hours', ...
        self.at_time = None  # optional time at which this job runs
        self.between_times = ()
        self.run_days = []
        self.start_run = None  # datetime after which this job will start
        self.last_run = None  # datetime of the last run
        self.next_run = None  # datetime of the next run
        self.period = None  # timedelta between runs, only valid for

    def __lt__(self, other):
        """PeriodicJobs are sortable based on the scheduled time
        they run next."""
        return self.next_run < other.next_run

    def __repr__(self):
        def format_time(t):
            return t.strftime("%Y-%m-%d %H:%M:%S") if t else '[never]'

        timestats = '(last run: %s, next run: %s)' % (
                    format_time(self.last_run), format_time(self.next_run))

        job_func_name = self.job_func.__name__
        args = [repr(x) for x in self.job_func.args]
        kwargs = ['%s=%s' % (k, repr(v))
                  for k, v in self.job_func.keywords.items()]
        call_repr = job_func_name + '(' + ', '.join(args + kwargs) + ')'

        if self.run_days:
            final_days = []
            for day in self.run_days:
                days_str = [k.title() for k, i in Job.WEEKDAYS.items()
                            for d in day if i == d]
                final_days.append(' or '.join(days_str))
            repr_str = 'Every %s' % ' and '.join(final_days)
        else:
            repr_str = 'Every %s %s' % (
                self.interval,
                self.unit[:-1] if self.interval == 1 else self.unit)

        if self.between_times:
            repr_str += ' between %s and %s' % (
                self.between_times[0].time(), self.between_times[1].time())
        elif self.at_time:
            repr_str += ' at %s' % self.at_time
        if self.start_run:
            repr_str += ' starting %s' % self.start_run
        repr_str += ' do %s %s' % (call_repr, timestats)
        return repr_str

    @property
    def second(self):
        assert self.interval == 1
        return self.seconds

    @property
    def seconds(self):
        self.unit = 'seconds'
        return self

    @property
    def minute(self):
        assert self.interval == 1
        return self.minutes

    @property
    def minutes(self):
        self.unit = 'minutes'
        return self

    @property
    def hour(self):
        assert self.interval == 1
        return self.hours

    @property
    def hours(self):
        self.unit = 'hours'
        return self

    @property
    def day(self):
        assert self.interval == 1
        return self.days

    @property
    def days(self):
        self.unit = 'days'
        return self

    @property
    def week(self):
        assert self.interval == 1
        return self.weeks

    @property
    def weeks(self):
        self.unit = 'weeks'
        return self

    def on(self, *days):
        """Schedule the job to run on specific weekdays.

        `days` can be a string (or sequence of strings) with the name of the
        weekday (case insensitive), e.g. 'Monday', 'sunday', etc, or a starting
        substring of the name of the weekday, e.g.  'tue', 'Sat', etc.

        If you specify multiple days, e.g. ('mon', 'wed'), the job will run
        every Monday and Wednesday.

        You can also specify OR conditions by separating the day names with a
        pipe, e.g. ('sun|mon', 'wed|thu'). In this case the job will run
        every Sunday *or* Monday, and every Wednesday *or* Thursday.
        """
        weeknums = []
        for day in days:
            day_or = set()
            for d in day.split('|'):
                for n, i in Job.WEEKDAYS.items():
                    if n.startswith(d.lower()):
                        day_or.add(i)
            if day_or:
                weeknums.append(day_or)

        self.run_days = weeknums
        return self

    def at(self, time_str):
        """Schedule the job every day at a specific time.

        Calling this is only valid for jobs scheduled to run every
        N day(s).
        """
        assert self.unit == 'days'
        hour, minute = [int(t) for t in time_str.split(':')]
        assert 0 <= hour <= 23
        assert 0 <= minute <= 59
        self.at_time = datetime.time(hour, minute)
        return self

    def between(self, time_str):
        """Schedule the job at a random time between two timestamps."""
        start, end = [datetime.datetime.strptime(t, '%H:%M')
                      for t in time_str.split('-')]
        self.between_times = (start, end)
        return self

    def starting(self, date_str):
        self.start_run = datetime.datetime.strptime(date_str, '%Y-%m-%d')
        return self

    def do(self, job_func, *args, **kwargs):
        """Specifies the job_func that should be called every time the
        job runs.

        Any additional arguments are passed on to job_func when
        the job runs.
        """
        self.job_func = functools.partial(job_func, *args, **kwargs)
        functools.update_wrapper(self.job_func, job_func)
        self._schedule_next_run()
        logger.info('Scheduled job %s', self)
        return self

    @property
    def should_run(self):
        """True if the job should be run now."""
        return datetime.datetime.now() >= self.next_run

    def run(self):
        """Run the job and immediately reschedule it."""
        logger.info('Running job %s', self)
        self.job_func()
        self.last_run = datetime.datetime.now()
        self._schedule_next_run()

    def _schedule_next_run(self):
        """Compute the instant when this job should run next."""
        # Allow *, ** magic temporarily:
        # pylint: disable=W0142
        assert self.unit in ('seconds', 'minutes', 'hours', 'days', 'weeks')
        starting = self.start_run or datetime.datetime.now()

        self.period = datetime.timedelta(**{self.unit: self.interval})
        self.next_run = starting + self.period

        if self.run_days:
            run_days = self.run_days[:]
            if self.last_run:
                starting = self.last_run
                # Don't consider this day group if it has been run already
                for day in self.run_days:
                    if self.last_run.isoweekday() in day:
                        run_days.remove(day)

            days = set()
            for day in run_days:
                days.add(random.sample(day, 1)[0])

            if not days:
                days_delta = 0
            else:
                # Calculate the closest day from the starting date
                delta_all = sorted([(i - starting.isoweekday()) % 7
                                    for i in days])
                days_delta = delta_all[0]

            if (days_delta == 0 and self.last_run and
                    self.last_run.date() == starting.date()):
                # Make sure the job doesn't run today twice
                if self.unit == 'days':
                    days_delta = 7
                elif self.unit == 'weeks':
                    days_delta = self.interval * 7
            self.next_run = starting + datetime.timedelta(days=days_delta)

        if self.between_times:
            start, end = self.between_times
            # Choose a random time between both timestamps
            self.at_time = (start + datetime.timedelta(
                seconds=random.randint(0, int(
                    (end - start).total_seconds())))).time()
        if self.at_time:
            self.next_run = self.next_run.replace(hour=self.at_time.hour,
                                                  minute=self.at_time.minute,
                                                  second=self.at_time.second,
                                                  microsecond=0)
            # If we are running for the first time, make sure we run
            # at the specified time *today* as well
            if (not self.last_run and not self.run_days and
                    self.at_time > datetime.datetime.now().time()):
                self.next_run = self.next_run - datetime.timedelta(days=1)


# The following methods are shortcuts for not having to
# create a Scheduler instance:

default_scheduler = Scheduler()
jobs = default_scheduler.jobs  # todo: should this be a copy, e.g. jobs()?


def every(interval=1):
    """Schedule a new periodic job."""
    return default_scheduler.every(interval)


def on(*days):
    """Schedule a new job to run on specific weekdays.

    See the docstring for `Job.on()`.
    """
    return default_scheduler.on(*days)


def run_pending():
    """Run all jobs that are scheduled to run.

    Please note that it is *intended behavior that run_pending()
    does not run missed jobs*. For example, if you've registered a job
    that should run every minute and you only call run_pending()
    in one hour increments then your job won't be run 60 times in
    between but only once.
    """
    default_scheduler.run_pending()


def run_all(delay_seconds=0):
    """Run all jobs regardless if they are scheduled to run or not.

    A delay of `delay` seconds is added between each job. This can help
    to distribute the system load generated by the jobs more evenly over
    time."""
    default_scheduler.run_all(delay_seconds=delay_seconds)


def clear():
    """Deletes all scheduled jobs."""
    default_scheduler.clear()


def next_run():
    """Datetime when the next job should run."""
    return default_scheduler.next_run


def idle_seconds():
    """Number of seconds until `next_run`."""
    return default_scheduler.idle_seconds
