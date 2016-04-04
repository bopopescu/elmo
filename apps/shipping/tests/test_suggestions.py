# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import datetime
import itertools
from nose.tools import eq_, ok_
from django.core.urlresolvers import reverse
from django.test import TestCase
from django.contrib.auth.models import User, Permission
from django.utils import simplejson as json
from commons.tests.mixins import EmbedsTestCaseMixin
from shipping.models import (
    Milestone,
    AppVersion,
    Action,
    Signoff,
    Application,
    AppVersionTreeThrough
)
from shipping import api
from life.models import (
    Locale,
    Push,
    Repository,
    Branch,
    Changeset,
    Tree,
    Forest
)
from l10nstats.models import Run, Active
from shipping.views.signoff import SignoffView
from shipping.views import teamsnippet


class DataMixin(object):
    """Generate generic data items for test cases."""

    (NEEDS_UPDATE, SUGGESTED, PENDING,
     HAS_SIGNOFF, REJECTED) = [2**i for i in range(5)]

    def base(self):
        self.locale = Locale.objects.create(code='de')
        self.app = Application.objects.create(name='Firefox', code='fx')
        self.peter = User.objects.create_user(
            'peter', 'peter@mozilla.com', 'secret'
        )
        self.axel = User.objects.create_user(
            'axel', 'axel@mozilla.com', 'secret'
        )
        self._now = datetime.datetime.utcnow() - datetime.timedelta(days=14)
        self.fallback = None

    def now(self):
        "Return an incremented time stamp"
        now = self._now
        self._now = self._now + datetime.timedelta(days=.5)
        return now

    def create_repo(self, forest_name='l10n'):
        """Create a life.models.Forest of the given name,
        and a life.models.Repository for self.locale in there.
        Also generate a life.models.Tree for the forest, and return
        both repository and forest.
        """
        forest = Forest.objects.create(
            name=forest_name,
            url='http://localhost:8001/%s/' % forest_name)
        repo = Repository.objects.create(
            name=forest_name + '/' + self.locale.code,
            url=forest.url + self.locale.code + '/',
            forest=forest,
            locale=self.locale)
        repo.changesets = (Changeset.objects
            .filter(revision__startswith="000000000000"))
        tree = Tree.objects.create(code='fx_' + forest.name, l10n=forest)
        return repo, tree

    def add_changesets(self, repo, count=1):
        """Add a number of changesets to the given repository and return them.

        Can be called several times.
        """
        n = repo.changesets.count() - 1
        parent = repo.changesets.order_by('-pk')[0]
        changesets = []
        for i in xrange(count):
            cs = Changeset.objects.create(
                revision='%s-123-%d' % (self.locale.code, i + n),
                user='user@example.tld',
                description='Description%d' % (i + n),
            )
            cs.parents.add(parent)
            changesets.append(cs)
            parent = cs
        repo.changesets.add(*changesets)
        return changesets

    def add_push(self, push_id, changesets, user="Bob", repository=None,
                 push_date=None):
        """Add a push with the given push_id and changesets to the
        repository. Return the push.

        repository defaults to self.repo
        push_date defaults to self.now()
        """
        if push_date is None:
            push_date = self.now()
        try:
            push_id = push_id.next()
        except AttributeError:
            pass
        push = Push.objects.create(
            user=user,
            repository=repository or self.repo,
            push_date=push_date,
            push_id=push_id)
        if type(changesets) == Changeset:
            changesets = [changesets]
        push.changesets.add(*changesets)
        return push

    def add_run(self, push, tree=None, **rundata):
        """Add a run for self.locale and self.tree (unless overridden).
        Returns the run.

        The revisions associated with the run are the ones of the push.
        The keyword arguments need to be valid keyword arguments to
        l10nstats.models.Run.
        """
        run = Run.objects.create(
            locale=self.locale,
            tree=tree or self.tree,
            build=None,
            srctime=push.push_date,
            **rundata
        )
        run.revisions = push.changesets.all()
        run.activate()
        self.latest_run = run
        return run

    def add_signoff(self, push, flag, av=None):
        """Add a Signoff to the given push, with the given flag.
        Returns the Signoff.

        Optionally specify the AppVersion to sign off on.
        """
        signoff = Signoff.objects.create(
            push=push,
            appversion=av or self.av,
            author=self.axel,
            locale=self.locale,
        )
        Action.objects.create(
            signoff=signoff,
            flag=Action.PENDING,
            author=self.axel,
        )
        if flag != Action.PENDING:
            Action.objects.create(
                signoff=signoff,
                flag=flag,
                author=self.peter,
            )
        return signoff


class TeamSnippetTest(TestCase, DataMixin):
    """Test the team page snippet data without fallbacks or migrations.
    """

    def setUp(self):
        """Set up test fixture:
        One locale, repo, tree, appversion.
        5 Changesets, first predating the appversion, with a run
        to ensure that the locale is active.
        The remaining changesets get a push each.
        """
        self.base()
        self.repo, self.tree = self.create_repo()
        self.av = AppVersion.objects.create(
            app=self.app,
            version='1.0',
            code='fx1.0',
            accepts_signoffs=True,
        )
        changesets = self.add_changesets(self.repo, 5)
        push = Push.objects.create(
            user="Bob",
            repository=self.repo,
            push_date=self.now(),
            push_id=1)
        push.changesets.add(changesets[0])
        self.add_run(
            push,
            total=100,
            changed=80,
            completion=80
        )
        AppVersionTreeThrough.objects.create(
            start=self.now(),
            tree=self.tree,
            appversion=self.av,
            end=None,
        )

        self.pushes = [push]
        for i, change in enumerate(changesets[1:]):
            push = Push.objects.create(
                user='Bob',
                repository=self.repo,
                push_date=self.now(),
                push_id=i + 1
            )
            push.changesets.add(change)
            self.pushes.append(push)

    def check_runs_and_get(self, runs):
        """Subclass this if you run these tests on more than one run."""
        eq_(len(runs), 1)
        return runs[0]

    def process(self, flags):
        context = teamsnippet(self.locale, [])['context']
        ok_('applications' in context)
        eq_(len(context['applications']), 1)
        application, runs = context['applications'][0]
        eq_(application, self.app)
        run = self.check_runs_and_get(runs)
        eq_(run['appversion'], self.av)
        eq_(run['tree'], self.tree)
        eq_(bool(run['is_active']), not(flags & self.NEEDS_UPDATE))
        eq_(bool(run['accepted']),
            bool(flags & self.HAS_SIGNOFF) or bool(self.fallback))
        eq_(bool(run['under_review']), bool(flags & self.PENDING))
        if flags & self.SUGGESTED:
            eq_(run['is_active'], True)
            eq_(run['suggested_shortrev'],
                self.latest_run.revisions.all()[0].shortrev)
            eq_(run['suggest_class'],
                'error' if self.latest_run.errors else
                'warning' if self.latest_run.allmissing else 'success')
            eq_(run['suggest_glyph'],
                'bolt' if self.latest_run.errors else
                'graph' if self.latest_run.allmissing else 'badge')
        else:
            eq_(run['suggested_shortrev'], None)
            eq_(run['suggest_class'], None)
            eq_(run['suggest_glyph'], None)
        signed = [a for a in (run.actions or []) if a.flag_name == 'accepted']
        eq_(len(signed), 0)
        if flags & self.REJECTED:
            pass
        # TODO: Test more actions
        # TODO: Fallback

    def test_no_progress(self):
        self.process(self.NEEDS_UPDATE)

    def test_2nd_pending(self):
        # Let's make an accepted signoff on the 2nd push
        push = self.pushes[1]
        self.add_run(
            push,
            total=100,
            changed=80,
            completion=80
        )
        self.add_signoff(push, Action.PENDING)
        self.process(self.PENDING)

    def test_2nd_accepted(self):
        # Let's make an accepted signoff on the 2nd push
        push = self.pushes[1]
        self.add_run(
            push,
            total=100,
            changed=80,
            completion=80
        )
        self.add_signoff(push, Action.ACCEPTED)
        self.process(self.HAS_SIGNOFF)

    def test_2nd_suggested(self):
        # Let's make an accepted signoff on the 2nd push
        push = self.pushes[1]
        self.add_run(
            push,
            total=100,
            changed=80,
            completion=80
        )
        self.process(self.SUGGESTED)

    def test_2nd_suggested_with_missing(self):
        # Let's make an accepted signoff on the 2nd push
        push = self.pushes[1]
        self.add_run(
            push,
            total=100,
            changed=40,
            completion=40,
            missing=20
        )
        self.process(self.SUGGESTED)

    def test_2nd_suggested_with_error(self):
        # Let's make an accepted signoff on the 2nd push
        push = self.pushes[1]
        self.add_run(
            push,
            total=100,
            changed=40,
            completion=40,
            errors=1,
            missing=20
        )
        self.process(self.SUGGESTED)

    def test_2nd_accepted_3rd_good(self):
        # Let's make an accepted signoff on the 2nd push
        push = self.pushes[1]
        self.add_run(
            push,
            total=100,
            changed=80,
            completion=80
        )
        self.add_signoff(push, Action.ACCEPTED)
        self.add_run(
            self.pushes[2],
            total=100,
            changed=80,
            completion=80
        )
        self.process(self.HAS_SIGNOFF | self.SUGGESTED)

    def test_2nd_rejected(self):
        # Let's make an rejected signoff on the 2nd push
        push = self.pushes[1]
        self.add_run(
            push,
            total=100,
            changed=80,
            completion=80
        )
        self.add_signoff(push, Action.REJECTED)
        self.process(self.REJECTED)

    def test_2nd_rejected_3rd_rejected(self):
        # Let's make an rejected signoff on the 2nd push
        push = self.pushes[1]
        self.add_run(
            push,
            total=100,
            changed=80,
            completion=80
        )
        self.add_signoff(push, Action.REJECTED)
        # this run is needed, see bug 1246207
        self.add_run(
            self.pushes[3],
            total=100,
            changed=80,
            completion=80
        )
        self.add_signoff(self.pushes[3], Action.REJECTED)
        self.process(self.REJECTED)

    def test_2nd_rejected_3rd_accepted(self):
        # Let's make an rejected signoff on the 2nd push
        push = self.pushes[1]
        self.add_run(
            push,
            total=100,
            changed=80,
            completion=80
        )
        self.add_signoff(push, Action.REJECTED)
        # this run is needed, see bug 1246207
        self.add_run(
            self.pushes[3],
            total=100,
            changed=80,
            completion=80
        )
        self.add_signoff(self.pushes[3], Action.ACCEPTED)
        self.process(self.HAS_SIGNOFF)

    def test_2nd_rejected_3rd_pending(self):
        # Let's make an rejected signoff on the 2nd push
        push = self.pushes[1]
        self.add_run(
            push,
            total=100,
            changed=80,
            completion=80
        )
        self.add_signoff(push, Action.REJECTED)
        # this run is needed, see bug 1246207
        self.add_run(
            self.pushes[3],
            total=100,
            changed=80,
            completion=80
        )
        self.add_signoff(self.pushes[3], Action.PENDING)
        self.process(self.REJECTED | self.PENDING)


class TeamSnippetMigrationTest(TestCase, DataMixin):
    '''Test for appversion with a migration

    Changes:          *   *   *    *   *
    Pushes to base:     |   |   |
    Pushes to beta:     |        |   |   |
    '''

    def setUp(self):
        self.base()
        self.repo, self.tree = self.create_repo()
        self.beta_repo, self.beta_tree = self.create_repo('beta')
        self.av = AppVersion.objects.create(
            app=self.app,
            version='1.0',
            code='fx1.0',
            accepts_signoffs=True,
        )
        self.next_av = AppVersion.objects.create(
            app=self.app,
            version='2.0',
            code='fx2.0',
            accepts_signoffs=False,
            fallback=self.av
        )
        changesets = self.add_changesets(self.repo, 5)
        # set up both base and beta to have active runs
        # before we do appversions, just so that they're active
        current_push_date = self.now()
        push_id = itertools.count(1)
        beta_push_id = itertools.count(1)
        push = self.add_push(push_id, changesets[0],
            push_date=current_push_date)
        self.add_run(
            push,
            total=100,
            changed=80,
            completion=80
        )
        self.pushes = [push]
        betapush = self.add_push(beta_push_id, changesets[0],
            repository=self.beta_repo,
            push_date=current_push_date)
        self.add_run(
            betapush,
            tree=self.beta_tree,
            total=100,
            changed=80,
            completion=80
        )
        self.beta_pushes = [betapush]
        self.pushes.append(self.add_push(push_id, changesets[1]))
        self.pushes.append(self.add_push(push_id, changesets[2]))
        # MERGE DAY!
        avt1 = AppVersionTreeThrough.objects.create(
            start=self.now(),
            tree=self.tree,
            appversion=self.av,
            end=None,
        )
        avt2 = AppVersionTreeThrough.objects.create(
            start=self.now(),
            tree=self.beta_tree,
            appversion=self.av,
            end=None)
        AppVersionTreeThrough.objects.create(
            start=avt2.start,
            tree=self.tree,
            appversion=self.next_av,
            end=None)
        avt1.end = avt2.start
        avt1.save()
        self.beta_pushes.append(self.add_push(beta_push_id,
            changesets[1:3],
            repository=self.beta_repo))
        # post-merge work on beta, maybe
        self.beta_pushes.append(self.add_push(beta_push_id,
            changesets[3],
            repository=self.beta_repo))
        self.beta_pushes.append(self.add_push(beta_push_id,
            changesets[4],
            repository=self.beta_repo))

    def check_runs_and_get(self, runs):
        eq_(len(runs), 2)
        for run in runs:
            if run['appversion'] == self.av:
                return run

    def process(self, **run_details):
        context = teamsnippet(self.locale, [])['context']
        ok_('applications' in context)
        eq_(len(context['applications']), 1)
        application, runs = context['applications'][0]
        eq_(application, self.app)
        run = self.check_runs_and_get(runs)
        for key, value in run_details.iteritems():
            ok_(key in run)
            eq_(run[key], value)

    def test_nothing(self):
        self.process(is_active=None, suggest_class=None)

    def test_good_on_merge(self):
        '''got a good run on the last changeset of base,
        same post-merge, no newer'''
        push = self.pushes[2]
        self.add_run(
            push,
            total=100,
            changed=80,
            completion=80
        )
        self.add_signoff(push, Action.ACCEPTED)
        beta_push = self.beta_pushes[1]
        self.add_run(
            beta_push,
            tree=self.beta_tree,
            total=100,
            changed=80,
            completion=80
        )
        self.process(
            is_active=True,
            suggest_class=None,
            suggest_glyph=None
        )

    def test_missing_on_merge(self):
        '''got a good run prior to the last changeset of base,
        same post-merge, no newer'''
        push = self.pushes[1]
        self.add_run(
            push,
            total=100,
            changed=80,
            completion=80
        )
        self.add_signoff(push, Action.ACCEPTED)
        beta_push = self.beta_pushes[1]
        self.add_run(
            beta_push,
            tree=self.beta_tree,
            total=100,
            changed=80,
            completion=80
        )
        self.process(
            is_active=True,
            suggested_shortrev=beta_push.tip.shortrev,
            suggest_class='success',
            suggest_glyph='badge'
        )

    def test_good_on_merge_and_more(self):
        '''got a good run on the last changeset of base,
        same post-merge, also newer'''
        push = self.pushes[2]
        self.add_run(
            push,
            total=100,
            changed=80,
            completion=80
        )
        self.add_signoff(push, Action.ACCEPTED)
        beta_push = self.beta_pushes[1]
        self.add_run(
            beta_push,
            tree=self.beta_tree,
            total=100,
            changed=80,
            completion=80
        )
        beta_push = self.beta_pushes[2]
        self.add_run(
            beta_push,
            tree=self.beta_tree,
            total=100,
            changed=80,
            completion=80
        )
        self.process(
            is_active=True,
            suggested_shortrev=beta_push.tip.shortrev,
            suggest_class='success',
            suggest_glyph='badge'
        )

    def test_missing_on_merge_and_more(self):
        '''got a good run prior to the last changeset of base,
        same post-merge, also newer'''
        push = self.pushes[1]
        self.add_run(
            push,
            total=100,
            changed=80,
            completion=80
        )
        self.add_signoff(push, Action.ACCEPTED)
        beta_push = self.beta_pushes[1]
        self.add_run(
            beta_push,
            tree=self.beta_tree,
            total=100,
            changed=80,
            completion=80
        )
        beta_push = self.beta_pushes[2]
        self.add_run(
            beta_push,
            tree=self.beta_tree,
            total=100,
            changed=80,
            completion=80
        )
        self.process(
            is_active=True,
            suggested_shortrev=beta_push.tip.shortrev,
            suggest_class='success',
            suggest_glyph='badge'
        )