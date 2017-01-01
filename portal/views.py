import base64
import traceback
import sys
import time
import subprocess

from flask import (flash, redirect, render_template, request,
                   session, url_for)


from portal import app, pages
from portal.decorators import authenticated, allocation_validated, project_exists
from portal.utils import (load_portal_client, get_safe_redirect,
                          get_vc3_client, project_validated, project_in_vc)

from vc3infoservice.core import InfoEntityExistsException


# Whitelist of Admin users

whitelist = ['c4686d14-d274-11e5-b866-0febeb7fd79e',
             'c3b990a0-d274-11e5-b641-934c1e30fc08',
             'f1f26455-cbd5-4933-986b-47c57ee20987',
             'be58c8e2-fc13-11e5-82f7-f7141a8b0c16',
             'f79bc072-c1f4-412f-a813-00ff11760062',
             '05e05adf-e9d4-487f-8771-b6b8a25e84d3',
             'a877729e-d274-11e5-a5d2-2f448d5a1c26',
             'c887eb90-d274-11e5-bf28-779c8998e810',
             'c456b77c-d274-11e5-b82c-23a245a48997',
             'c444a294-d274-11e5-b7f1-e3782ed16687',
             'aebe29b8-d274-11e5-ba4b-ffec0df955f2']

whitelist_email = ['jeremyvan@uchicago.edu', 'briedel@uchicago.edu',
                   'btovar@nd.edu', 'burt@fnal.gov', 'czheng2@nd.edu',
                   'dthain@nd.edu', 'jcaballero@bnl.gov',
                   'jgentle@tacc.utexas.edu', 'jhover@bnl.gov',
                   'khurtado@nd.edu', 'Kyle.D.Sweeney.84@nd.edu',
                   'lincolnb@uchicago.edu', 'nhazekam@nd.edu',
                   'rwg@uchicago.edu', 'sthapa@ci.uchicago.edu',
                   'tshaffe1@nd.edu', 'czheng2@nd.edu', 'pivie@nd.edu',
                   'jlstephen@uchicago.edu', 'dbala@uchicago.edu',
                   'gfarr@uchicago.edu']

# Create a custom error handler for Exceptions


@app.errorhandler(Exception)
def exception_occurred(e):
    trace = traceback.format_tb(sys.exc_info()[2])
    app.logger.error("{0} Traceback occurred:\n".format(time.ctime()) +
                     "{0}\nTraceback completed".format("n".join(trace)))
    trace = "<br>".join(trace)
    trace.replace('\n', '<br>')
    return render_template('error.html', exception=trace,
                           debug=app.config['DEBUG'])


@app.errorhandler(LookupError)
def missing_object_error_page(e):
    return render_template('missing_entity.html')


@app.route('/', methods=['GET'])
def home():
    """Home page - play with it if you must!"""
    return render_template('home.html')


@app.route('/status', methods=['GET', 'POST'])
def status():
    """Status page - to display System Operational Status"""
    return render_template('status.html')

# -----------------------------------------
# CURRENT blog PAGE AND ALL ARTICLE ROUTES
# -----------------------------------------


@app.route('/blog', methods=['GET'])
def blog():
    """Articles are pages with a publication date"""
    articles = (p for p in pages if 'date' in p.meta)
    """Show the 10 most recent articles, most recent first"""
    latest = sorted(articles, reverse=True, key=lambda p: p.meta['date'])
    blog_pages = latest[:10]
    taglist = []
    for p in blog_pages:
        if p.meta['tags'][0] not in taglist:
            taglist.append(p.meta['tags'][0])
    """Send the user to the blog page"""
    return render_template('blog.html', pages=blog_pages, taglist=taglist)


@app.route('/blog/tag/<string:tag>/', methods=['GET'])
def tag(tag):
    """Automatic routing and compiling for article tags"""
    tagged = [p for p in pages if tag in p.meta.get('tags', [])]
    return render_template('blog_tag.html', pages=tagged, tag=tag)


@app.route('/blog/<path:path>/', methods=['GET'])
def page(path):
    """Automatic routing and generates markdown flatpages in /pages directory"""
    page_path = pages.get_or_404(path)
    return render_template('blog_page.html', page=page_path)


@app.route('/community', methods=['GET'])
def community():
    """Send the user to community page"""
    return render_template('community.html')


@app.route('/documentations', methods=['GET'])
def documentations():
    """Send the user to documentations page"""
    return render_template('documentations.html')


@app.route('/team', methods=['GET'])
def team():
    """Send the user to team page"""
    return render_template('team.html')


@app.route('/signup', methods=['GET'])
def signup():
    """Send the user to Globus Auth with signup=1."""
    return redirect(url_for('authcallback', signup=1))


@app.route('/login', methods=['GET'])
def login():
    """Send the user to Globus Auth."""
    return redirect(url_for('authcallback'))


@app.route('/logout', methods=['GET'])
@authenticated
def logout():
    """
    - Revoke the tokens with Globus Auth.
    - Destroy the session state.
    - Redirect the user to the Globus Auth logout page.
    """
    globusclient = load_portal_client()

    # Revoke the tokens with Globus Auth
    for token, token_type in (
            (token_info[ty], ty)
            # get all of the token info dicts
            for token_info in session['tokens'].values()
            # cross product with the set of token types
            for ty in ('access_token', 'refresh_token')
            # only where the relevant token is actually present
            if token_info[ty] is not None):
        globusclient.oauth2_revoke_token(
            token, additional_params={'token_type_hint': token_type})

    # Destroy the session state
    session.clear()

    redirect_uri = url_for('home', _external=True)

    ga_logout_url = []
    ga_logout_url.append(app.config['GLOBUS_AUTH_LOGOUT_URI'])
    ga_logout_url.append('?client={}'.format(app.config['PORTAL_CLIENT_ID']))
    ga_logout_url.append('&redirect_uri={}'.format(redirect_uri))
    ga_logout_url.append('&redirect_name=VC3 Home')

    # Redirect the user to the Globus Auth logout page
    # return redirect(''.join(ga_logout_url))
    return redirect(url_for('home'))


@app.route('/profile', methods=['GET', 'POST'])
@authenticated
def show_profile_page():
    """User profile information. Assocated with a Globus Auth identity."""

    vc3_client = get_vc3_client()
    userlist = vc3_client.listUsers()
    projects = vc3_client.listProjects()
    nodesets = vc3_client.listNodesets()
    virtualclusters = vc3_client.listRequests()

    if request.method == 'GET':
        profile = None
        sshpubstring = None
        name = None
        user_projects = 0
        user_virtualclusters = 0
        user_nodes = 0

        for user in userlist:
            if session['primary_identity'] == user.identity_id:
                profile = user

        if profile:

            name = session['name'] = profile.name
            session['displayname'] = profile.displayname
            session['first'] = profile.first
            session['last'] = profile.last
            session['email'] = profile.email
            session['institution'] = profile.organization
            session['primary_identity'] = profile.identity_id
            if profile.sshpubstring is not None:
                sshpubstring = profile.sshpubstring
            for project in projects:
                if profile.name in project.members:
                    user_projects += 1
            for vc in virtualclusters:
                if profile.name == vc.owner:
                    user_virtualclusters += 1
            for nodeset in nodesets:
                if profile.name == nodeset.owner:
                    user_nodes += nodeset.node_number
        else:
            if session['email'] not in whitelist_email:
                return redirect(url_for('whitelist_error'))
                # pass
            else:
                flash('Please complete any missing profile fields before '
                      'launching a cluster.', 'warning')

        if request.args.get('next'):
            session['next'] = get_safe_redirect()

        return render_template('profile.html', userlist=userlist,
                               profile=profile, name=name,
                               user_projects=user_projects,
                               user_virtualclusters=user_virtualclusters,
                               user_nodes=user_nodes)
    elif request.method == 'POST':
        first = request.form['first']
        last = request.form['last']
        email = request.form['email']
        organization = request.form['institution']
        identity_id = session['primary_identity']
        displayname = first + ' ' + last
        sshpubstring_input = request.form['sshpubstring']
        sshpubstring = str(sshpubstring_input)

        # UNIX naming convention: no whitespace, lowercase, limit length to 14
        inputname = request.form['name']
        translatename = "".join(inputname.split())
        name = translatename.lower()

        try:
            newuser = vc3_client.defineUser(identity_id=identity_id,
                                            name=name,
                                            first=first,
                                            last=last,
                                            email=email,
                                            organization=organization,
                                            displayname=displayname,
                                            sshpubstring=sshpubstring)

            vc3_client.storeUser(newuser)
        except InfoEntityExistsException:
            flash('That username has already been chosen please choose another'
                  ' username', 'warning')
            return render_template('profile.html')
        except:
            flash('There was an unexpected error. Please try again later', ' error', 'warning')
            return render_template('profile.html')

        if not vc3_client.validate_ssh_pub_key(sshpubstring):
            flash('Your public ssh-key is not valid. Please try again.', ' ssh-key', 'warning')
            return render_template('profile.html')

        flash('Thank you. Your profile has been successfully updated. '
              'You may now register an allocation.', 'success')

        if 'next' in session:
            redirect_to = session['next']
            session.pop('next')
        else:
            redirect_to = url_for('portal')

        return redirect(redirect_to)


@app.route('/profile/edit/<name>', methods=['POST'])
@authenticated
def edit_profile(name):
    vc3_client = get_vc3_client()

    profile = None
    # Call user by name
    profile = vc3_client.getUser(username=name)
    # Assign new attribute to selected user
    if profile.name == name:
        profile.first = request.form['first']
        profile.last = request.form['last']
        profile.email = request.form['email']
        profile.organization = request.form['institution']

        displayname = (request.form['first'] + ' ' + request.form['last'])
        profile.displayname = displayname

        sshpubstring_input = request.form['sshpubstring']
        profile.sshpubstring = str(sshpubstring_input)

    if profile is None:
        # could not find user, punt
        LookupError('user')

    # Store user new attributes into infoservice
    vc3_client.storeUser(profile)
    # Redirect to updated  profile page
    flash('Your profile has been successfully updated', 'success')
    return redirect(url_for('show_profile_page'))


@app.route('/authcallback', methods=['GET'])
def authcallback():
    """Handles the interaction with Globus Auth."""
    # If we're coming back from Globus Auth in an error state, the error
    # will be in the "error" query string parameter.

    if 'error' in request.args:
        flash("You could not be logged into the portal: " +
              request.args.get('error_description', request.args['error']))
        return redirect(url_for('home'))

    # Set up our Globus Auth/OAuth2 state
    redirect_uri = url_for('authcallback', _external=True)

    globusclient = load_portal_client()
    globusclient.oauth2_start_flow(redirect_uri, refresh_tokens=True)

    # If there's no "code" query string parameter, we're in this route
    # starting a Globus Auth login flow.
    if 'code' not in request.args:

        additional_authorize_params = (
            {'signup': 1} if request.args.get('signup') else {})

        auth_uri = globusclient.oauth2_get_authorize_url(
            additional_params=additional_authorize_params)

        return redirect(auth_uri)
    else:
        # If we do have a "code" param, we're coming back from Globus Auth
        # and can start the process of exchanging an auth code for a token.
        code = request.args.get('code')
        tokens = globusclient.oauth2_exchange_code_for_tokens(code)

        id_token = tokens.decode_id_token(globusclient)
        session.update(
            tokens=tokens.by_resource_server,
            is_authenticated=True,
            name=id_token.get('name', ''),
            email=id_token.get('email', ''),
            institution=id_token.get('institution', ''),
            primary_username=id_token.get('preferred_username'),
            primary_identity=id_token.get('sub'),
        )
        vc3_client = get_vc3_client()
        userlist = vc3_client.listUsers()
        profile = None

        ids = globusclient.get_identities(
            usernames=id_token.get('preferred_username', ''))

        email = id_token.get('email', '')
        # print(id_token.get('name', ''))
        # Restrict Email access to only .edu, .gov, and .org
        # User must have a valid institutional affiliation
        # Otherwise return to error page, explaining restricted access
        # identities = globusclient.get_identities(
        #     primary_username=id_token.get('preferred_username'))
        # for id in identities["identities"]:
        #     if id["username"].split("@")[-1].split(".")[-1] in ["edu", "gov", "org"]:
        #         inst_username = [id["username"].split("@")[-1].split(".")[-1]]
        #
        # if not inst_username:
        #     return render_template('email_error.html')

        if not (email.split("@")[-1].split(".")[-1] in ["edu", "gov", "org"]):
            return render_template('email_error.html')

        for user in userlist:
            if session['primary_identity'] == user.identity_id:
                profile = user

        if profile:

            session['name'] = profile.name
            session['first'] = profile.first
            session['last'] = profile.last
            session['email'] = profile.email
            session['institution'] = profile.organization
            session['primary_identity'] = profile.identity_id
            session['displayname'] = profile.displayname
        else:
            session['name'] = ids["identities"][0]['name']
            session['organization'] = ids["identities"][0]['organization']
            session['first'] = session['name'].split()[0]
            session['last'] = session['name'].split()[-1]
            return redirect(url_for('show_profile_page',
                                    next=url_for('show_profile_page')))
        if session['email'] not in whitelist_email:
            return redirect(url_for('whitelist_error'))
            # pass

        return redirect(url_for('portal'))


@app.route('/beta', methods=['GET'])
def whitelist_error():
    """Whitelist Erorr Page - for users not within alpha testing scope"""
    return render_template('whitelist_error.html')

# -----------------------------------------
# LOGGED IN PORTAL ROUTES
# -----------------------------------------


@app.route('/portal', methods=['GET'])
@authenticated
def portal():
    """Send the existing user to Portal Home."""
    vc3_client = get_vc3_client()
    userlist = vc3_client.listUsers()
    projects = vc3_client.listProjects()
    virtualclusters = vc3_client.listRequests()
    nodesets = vc3_client.listNodesets()
    resources = vc3_client.listResources()

    if request.method == 'GET':
        profile = None
        sshpubstring = None
        name = None
        user_projects = 0
        user_virtualclusters = 0
        user_nodes = 0

        for user in userlist:
            if session['primary_identity'] == user.identity_id:
                profile = user

        if profile:

            name = session['name'] = profile.name
            session['displayname'] = profile.displayname
            session['first'] = profile.first
            session['last'] = profile.last
            session['email'] = profile.email
            session['institution'] = profile.organization
            session['primary_identity'] = profile.identity_id
            if profile.sshpubstring is not None:
                sshpubstring = profile.sshpubstring
        else:
            # if session['primary_identity'] not in ["c887eb90-d274-11e5-bf28-779c8998e810", "05e05adf-e9d4-487f-8771-b6b8a25e84d3", "c4686d14-d274-11e5-b866-0febeb7fd79e", "be58c8e2-fc13-11e5-82f7-f7141a8b0c16", "c456b77c-d274-11e5-b82c-23a245a48997", "f1f26455-cbd5-4933-986b-47c57ee20987", "aebe29b8-d274-11e5-ba4b-ffec0df955f2", "c444a294-d274-11e5-b7f1-e3782ed16687", "9c1c1643-8726-414f-85dc-aca266099304"]:
            #     next
            # else:
            flash('Please complete any missing profile fields before '
                  'launching a cluster.', 'warning')

        for project in projects:
            if profile.name in project.members:
                user_projects += 1
        for vc in virtualclusters:
            if profile.name == vc.owner:
                user_virtualclusters += 1
        for nodeset in nodesets:
            if profile.name == nodeset.owner:
                user_nodes += nodeset.node_number

        if request.args.get('next'):
            session['next'] = get_safe_redirect()

        return render_template('portal_home.html', userlist=userlist,
                               profile=profile, name=name,
                               sshpubstring=sshpubstring,
                               user_projects=user_projects,
                               user_virtualclusters=user_virtualclusters,
                               user_nodes=user_nodes, resources=resources)


@app.route('/new', methods=['GET', 'POST'])
@authenticated
@allocation_validated
def create_project():
    """ Creating New Project Form """
    vc3_client = get_vc3_client()
    users = vc3_client.listUsers()
    allocations = vc3_client.listAllocations()
    if request.method == 'GET':
        owner = session['name']

        return render_template('project_new.html', owner=owner,
                               users=users, allocations=allocations)

    elif request.method == 'POST':
        # Method to define and store projects
        # along with associated members and allocations
        # Initial members and allocations not required
        projects = vc3_client.listProjects()
        name = request.form['name']
        owner = session['name']
        members = []

        if request.form['description'] == "":
            description = None
        else:
            description = request.form['description']

        try:
            newproject = vc3_client.defineProject(name=name, owner=owner,
                                                  members=members,
                                                  description=description)
            vc3_client.storeProject(newproject)
        except:
            description = request.form['description']
            flash('You have already created a project with that name, please '
                  'choose another project name', 'warning')
            return render_template('project_new.html', owner=owner,
                                   users=users, allocations=allocations,
                                   description=description)

        for selected_member in request.form.getlist('members'):
            vc3_client.addUserToProject(project=name, user=selected_member)
        for selected_allocation in request.form.getlist('allocation'):
            vc3_client.addAllocationToProject(allocation=selected_allocation,
                                              projectname=newproject.name)
        flash('Your project has been successfully created.', 'success')

        return redirect(url_for('list_projects'))


@app.route('/project', methods=['GET'])
@authenticated
def list_projects():
    """ Project List View """
    vc3_client = get_vc3_client()
    projects = vc3_client.listProjects()
    users = vc3_client.listUsers()
    allocations = vc3_client.listAllocations()

    return render_template('project.html', projects=projects, users=users, allocations=allocations)


@app.route('/project/<name>', methods=['GET'])
@authenticated
def view_project(name):
    """
    View Specific Project Profile View, with name passed in as argument

    :param name: name attribute of project
    :return: Project profile page specific to project name
    """
    project_validation = project_validated(name=name)
    if project_validation is False:
        flash('You do not appear to be a member of the project you are trying'
              'to view. Please contact owner to request membership.', 'warning')
        return redirect(url_for('list_projects'))

    vc3_client = get_vc3_client()
    projects = vc3_client.listProjects()
    allocations = vc3_client.listAllocations()
    users = vc3_client.listUsers()
    project = None

    # Scanning list of projects and matching with name of project argument

    project = vc3_client.getProject(projectname=name)
    if project:
        name = project.name
        owner = project.owner
        members = project.members
        project = project
        description = project.description
        # organization = project.organization
        return render_template('projects_pages.html', name=name, owner=owner,
                               members=members, allocations=allocations,
                               projects=projects, users=users, project=project,
                               description=description)
    app.logger.error("Could not find project when viewing: {0}".format(name))
    raise LookupError('project')


@app.route('/project/<name>/addmember', methods=['POST'])
@authenticated
def add_member_to_project(name):
    """
    Adding members to project from project profile page
    Only owner of project may add members to project

    :param name: name attribute of project
    :return: Project profile page specific to project name
    """

    vc3_client = get_vc3_client()
    projects = vc3_client.listProjects()

    user = request.form['newuser']

    for project in projects:
        if project.name == name:
            name = project.name
            if project.owner == user:
                flash('User is already the project owner.', 'warning')
                app.logger.error("Trying to add owner as member:" +
                                 "owner: {0} project:{1}".format(user, name))
                return redirect(url_for('view_project', name=name))
            for selected_member in request.form.getlist('newuser'):
                vc3_client.addUserToProject(project=name, user=selected_member)
            flash('Successfully added member to project.', 'success')
            return redirect(url_for('view_project', name=name))
    app.logger.error("Could not find project when adding user: " +
                     "user: {0} project:{1}".format(user, name))
    flash('Project not found, can\'t add user', 'warning')
    return redirect(url_for('view_project', name=name))


@app.route('/project/<name>/removemember', methods=['POST'])
@authenticated
def remove_member_from_project(name):
    """
    Removing members from project
    Only owner of project may remove members to project

    :param name: name attribute of project
    :return: Project profile page specific to project name
    """

    vc3_client = get_vc3_client()

    # Grab project by name and user is user.name from submit button
    project = vc3_client.getProject(projectname=name)
    user = request.form['submit']

    # List of user's allocations
    allocations = vc3_client.listAllocations()
    user_allocations = [a.name for a in allocations if user == a.owner]

    # Remove allocation if user has allocation in project
    for allocation in project.allocations:
        if allocation in user_allocations:
            vc3_client.removeAllocationFromProject(allocation=allocation, projectname=name)

    # Finally remove user from project entirely
    vc3_client.removeUserFromProject(user=user, project=project.name)

    return redirect(url_for('view_project', name=name))


@app.route('/project/<name>/addallocation', methods=['POST'])
@authenticated
def add_allocation_to_project(name):
    """
    Adding allocations to project from project profile page
    Only owner/members of project may add their own allocations to project

    :param name: name attribute of project to match
    :return: Project page specific to project name, with new allocation added
    """
    vc3_client = get_vc3_client()
    projects = vc3_client.listProjects()

    # new_allocation = request.form['allocation']

    for project in projects:
        if project.name == name:
            name = project.name
            for selected_allocation in request.form.getlist('allocation'):
                vc3_client.addAllocationToProject(allocation=selected_allocation,
                                                  projectname=name)
            flash('Successfully added allocation to project.', 'success')
            return redirect(url_for('view_project', name=name))
    app.logger.error("Could not find project when adding allocation: " +
                     "alloc: {0} project:{1}".format(new_allocation, name))
    flash('Project not found, could not add allocation to project', 'warning')
    return redirect(url_for('view_project', name=name))


@app.route('/project/<name>/removeallocation', methods=['POST'])
@authenticated
def remove_allocation_from_project(name):
    """
    Removing allocation from project
    Only owner of project and/or owner of allocation may remove allocations
    from said project

    :param name: name attribute of project
    :return: Project profile page specific to project name
    """

    vc3_client = get_vc3_client()
    remove_allocation = request.form['remove_allocation']

    vc3_client.removeAllocationFromProject(allocation=remove_allocation, projectname=name)
    flash('You have successfully removed allocation from this project', 'success')

    return redirect(url_for('view_project', name=name))


@app.route('/project/delete/<name>', methods=['GET'])
@authenticated
def delete_project(name):
    """
    Route for method to delete project

    :param name: name attribute of project to delete
    :return: Redirect to List Project page with project deleted
    """

    project_validation = project_validated(name=name)
    if project_validation == False:
        flash('You do not have the authority to delete this project.', 'warning')
        return redirect(url_for('list_projects'))

    vc3_client = get_vc3_client()

    # Grab project by name and delete entity

    project = vc3_client.getProject(projectname=name)
    vc3_client.deleteProject(projectname=project.name)
    flash('Project has been successfully deleted', 'success')

    return redirect(url_for('list_projects'))


@app.route('/cluster/new', methods=['GET', 'POST'])
@authenticated
def create_cluster():
    """ Create New Cluster Template Form """

    vc3_client = get_vc3_client()
    clusters = vc3_client.listClusters()
    projects = vc3_client.listProjects()
    nodesets = vc3_client.listNodesets()

    if request.method == 'GET':
        return render_template('cluster_new.html', clusters=clusters,
                               projects=projects, nodesets=nodesets)

    elif request.method == 'POST':
        # Assigning attribute variables by form input and presets
        # Create and save new nodeset first, followed by new cluster
        # and finally add said nodeset to the new cluster

        inputname = request.form['name']
        owner = session['name']
        node_number = request.form['node_number']
        app_type = request.form['app_type']
        app_role = "worker-nodes"
        translatename = "".join(inputname.split())
        name = owner + "-" + translatename.lower()
        displayname = translatename.lower()
        description_input = request.form['description']
        description = str(description_input)

        try:
            nodeset = vc3_client.defineNodeset(name=name, owner=owner,
                                               node_number=node_number, app_type=app_type,
                                               app_role=app_role, environment=None,
                                               displayname=displayname)
            vc3_client.storeNodeset(nodeset)
        except:
            node_number = request.form['node_number']
            app_type = request.form['app_type']
            description_input = request.form['description']
            description = str(description_input)
            framework = app_type
            flash('A cluster template with that name already exists.', 'warning')
            return render_template('cluster_new.html', clusters=clusters,
                                   projects=projects, nodesets=nodesets,
                                   description=description, node_number=node_number,
                                   framework=framework)

        newcluster = vc3_client.defineCluster(
            name=name, owner=owner, nodesets=[], description=description, displayname=displayname)
        vc3_client.storeCluster(newcluster)
        vc3_client.addNodesetToCluster(nodesetname=nodeset.name,
                                       clustername=newcluster.name)

        flash('Your cluster template has been successfully defined.', 'success')
        return redirect(url_for('list_clusters'))


@app.route('/cluster', methods=['GET'])
@authenticated
def list_clusters():
    """ List Cluster Template View """
    vc3_client = get_vc3_client()
    clusters = vc3_client.listClusters()
    projects = vc3_client.listProjects()
    nodesets = vc3_client.listNodesets()

    return render_template('cluster.html', clusters=clusters,
                           projects=projects, nodesets=nodesets)


@app.route('/cluster/<name>', methods=['GET'])
@authenticated
def view_cluster(name):
    """
    Specific page view, pertaining to Cluster Template

    :param name: name attribute of cluster
    :return: Cluster Template profile view specific to cluster name
    """
    vc3_client = get_vc3_client()
    clusters = vc3_client.listClusters()
    projects = vc3_client.listProjects()
    nodesets = vc3_client.listNodesets()
    users = vc3_client.listUsers()
    cluster = None

    cluster = vc3_client.getCluster(clustername=name)
    if cluster:
        cluster_name = cluster.name
        owner = cluster.owner
        state = cluster.state
        description = cluster.description
        displayname = cluster.displayname

        return render_template('cluster_profile.html', name=cluster_name,
                               owner=owner, state=state,
                               nodesets=nodesets, description=description,
                               users=users, clusters=clusters,
                               projects=projects, displayname=displayname)
    raise LookupError('cluster')


@app.route('/cluster/edit/<name>', methods=['GET', 'POST'])
@authenticated
def edit_cluster(name):
    """
    Edit Page for specific cluster templates
    Only owner of cluster template may make edits to cluster template

    :param name: name attribute of cluster template to match
    :return: Edit Page with information pertaining to the cluster template
    """
    vc3_client = get_vc3_client()
    clusters = vc3_client.listClusters()
    projects = vc3_client.listProjects()
    nodesets = vc3_client.listNodesets()
    frameworks = []

    if request.method == 'GET':
        for cluster in clusters:
            if cluster.name == name:
                clustername = cluster.name
                owner = cluster.owner
                state = cluster.state
                description = cluster.description
        for nodeset in nodesets:
            if nodeset.name == name:
                node_number = nodeset.node_number
                framework = nodeset.app_type
                if nodeset.app_type not in frameworks:
                    frameworks.append(nodeset.app_type)

                return render_template('cluster_edit.html', name=clustername,
                                       owner=owner, nodesets=nodesets,
                                       state=state, projects=projects,
                                       frameworks=frameworks, node_number=node_number,
                                       description=description, framework=framework)
        app.logger.error("Could not find cluster when editing: {0}".format(name))
        raise LookupError('cluster')

    elif request.method == 'POST':
        # Grab new framework from form
        # app_type = request.form['app_type']

        cluster_name = None
        # Call cluster and nodeset by name
        cluster = vc3_client.getCluster(clustername=name)
        nodeset = vc3_client.getNodeset(nodesetname=name)
        # Assign new attribute to selected cluster
        if cluster.name == name:
            cluster_name = cluster.name
            cluster.description = request.form['description']
            nodeset.node_number = request.form['node_number']
            nodeset.app_type = request.form['app_type']
        if cluster_name is None:
            # could not find cluster, punt
            LookupError('cluster')

        # if app_type == "htcondor":
        #     nodeset.environment = "condor-glidein-password-env1"
        # elif app_type == "workqueue":
        #     nodeset.environment = []
        # else:
        #     app.logger.error("Got unsupported framework when viewing " +
        #                      "cluster template: {0}".format(app_type))
        #     raise ValueError('app_type not a recognized framework')
        # Store nodeset and cluster with new attributes into infoservice
        vc3_client.storeNodeset(nodeset)
        vc3_client.storeCluster(cluster)
        # Redirect to updated cluster profile page
        flash('Cluster has been successfully updated', 'success')
        return redirect(url_for('view_cluster', name=name))


@app.route('/cluster/delete/<name>', methods=['GET'])
@authenticated
def delete_cluster(name):
    """
    Route for method to delete cluster template

    :param name: name attribute of cluster template to delete
    :return: Redirect to List Cluster Template page with cluster template deleted
    """
    vc3_client = get_vc3_client()

    # Grab nodeset associated with cluster template and delete entity

    nodeset = vc3_client.getNodeset(nodesetname=name)
    vc3_client.deleteNodeset(nodesetname=nodeset.name)

    # Finally grab cluster template and delete entity

    cluster = vc3_client.getCluster(clustername=name)
    vc3_client.deleteCluster(clustername=cluster.name)
    flash('Cluster Template has been successfully deleted', 'success')

    return redirect(url_for('list_clusters'))


@app.route('/allocation', methods=['GET'])
@authenticated
def list_allocations():
    """ List Allocations Page """
    vc3_client = get_vc3_client()
    allocations = vc3_client.listAllocations()
    resources = vc3_client.listResources()
    projects = vc3_client.listProjects()
    users = vc3_client.listUsers()
    allocation_list = []

    for allocation in allocations:
        if allocation.owner == session['name']:
            allocation_list.append(str(allocation.name))

    return render_template('allocation.html', allocations=allocations,
                           resources=resources, users=users, projects=projects,
                           allocationlist=allocation_list)


@app.route('/allocation/new', methods=['GET', 'POST'])
@authenticated
def create_allocation():
    """ New Alloation Creation Form """
    vc3_client = get_vc3_client()
    if request.method == 'GET':
        resources = vc3_client.listResources()
        return render_template('allocation_new.html', resources=resources)

    elif request.method == 'POST':
        # Gathering and storing information from new allocation form
        # into info-service
        # Description from text input stored as string to avoid malicious input

        displayname = request.form['displayname']
        owner = session['name']
        resource = request.form['resource']
        accountname = request.form['accountname']
        allocationname = owner + "." + resource
        name = allocationname.lower()
        description_input = request.form['description']
        description = str(description_input)
        # url = request.form['url']
        try:
            newallocation = vc3_client.defineAllocation(
                name=name, owner=owner, resource=resource, accountname=accountname,
                displayname=displayname, description=description)
            vc3_client.storeAllocation(newallocation)
        except:
            displayname = request.form['displayname']
            accountname = request.form['accountname']
            description_input = request.form['description']
            description = str(description_input)
            resources = vc3_client.listResources()
            flash('You have already registered an allocation on that resource.', 'warning')
            return render_template('allocation_new.html', displayname=displayname,
                                   accountname=accountname, description=description,
                                   resources=resources)

        flash('Configuring your allocation, when validated, please view your '
              'allocation to complete the setup.', 'warning')

        return redirect(url_for('list_allocations'))


@app.route('/allocation/<name>', methods=['GET', 'POST'])
@authenticated
# @allocation_validated
def view_allocation(name):
    """
    Allocation Detailed Page View

    :param name: name attribute of allocation
    :return: Allocation detailed page with associated attributes
    """
    vc3_client = get_vc3_client()
    allocations = vc3_client.listAllocations()
    resources = vc3_client.listResources()
    users = vc3_client.listUsers()

    if request.method == 'GET':
        for allocation in allocations:
            if allocation.name == name:
                allocationname = allocation.name
                owner = allocation.owner
                resource = allocation.resource
                state = allocation.state
                displayname = allocation.displayname
                description = allocation.description
                accountname = allocation.accountname
                encodedpubtoken = allocation.pubtoken
                if encodedpubtoken is None:
                    pubtoken = 'None'
                else:
                    pubtoken = base64.b64decode(encodedpubtoken)
                for r in resources:
                    if r.name == allocation.resource:
                        accesshost = r.accesshost

                return render_template('allocation_profile.html',
                                       name=allocationname,
                                       owner=owner, resource=resource,
                                       accountname=accountname,
                                       pubtoken=pubtoken, state=state,
                                       resources=resources, displayname=displayname,
                                       description=description, users=users,
                                       accesshost=accesshost)
        app.logger.error("Could not find allocation when viewing: {0}".format(name))
        raise LookupError('allocation')

    elif request.method == 'POST':
        # Iterate through allocations list in infoservice for allocation
        # with the matching name argument and update with new form input

        for allocation in allocations:
            if allocation.name == name:
                allocationname = allocation.name
                owner = allocation.owner
                resource = request.form['resource']
                accountname = request.form['accountname']
                # displayname = request.form['displayname']
                # description_input = request.form['description']
                # description = str(description_input)

                newallocation = vc3_client.defineAllocation(name=allocationname,
                                                            owner=owner,
                                                            resource=resource,
                                                            accountname=accountname)
                vc3_client.storeAllocation(newallocation)
                flash('Allocation created', 'success')
                return render_template('allocation_profile.html', name=allocationname,
                                       owner=owner, accountname=accountname,
                                       resource=resource, allocations=allocations,
                                       resources=resources)


@app.route('/allocation/edit/<name>', methods=['GET', 'POST'])
@authenticated
@allocation_validated
def edit_allocation(name):
    vc3_client = get_vc3_client()
    allocations = vc3_client.listAllocations()
    resources = vc3_client.listResources()

    allocation = vc3_client.getAllocation(allocationname=name)

    if request.method == 'GET':
        if allocation.name == name:
            allocationname = allocation.name
            owner = allocation.owner
            resource = allocation.resource
            accountname = allocation.accountname
            pubtoken = allocation.pubtoken
            description = allocation.description
            displayname = allocation.displayname

            return render_template('allocation_edit.html', name=allocationname,
                                   owner=owner, resources=resources,
                                   resource=resource, accountname=accountname,
                                   pubtoken=pubtoken, description=description,
                                   displayname=displayname)
        app.logger.error("Could not find allocation when editing: {0}".format(name))
        raise LookupError('alliocation')

    elif request.method == 'POST':
        allocation = vc3_client.getAllocation(allocationname=name)
        if allocation.name == name:
            allocation.description = request.form['description']
            allocation.displayname = request.form['displayname']

        vc3_client.storeAllocation(allocation)
        flash('Allocation successfully updated', 'success')
        return redirect(url_for('view_allocation', name=name))


@app.route('/allocation/delete/<name>', methods=['GET'])
@authenticated
def delete_allocation(name):
    """
    Route for method to delete allocation

    :param name: name attribute of allocation to delete
    :return: Redirect to List Allocation page with Allocation deleted
    """
    vc3_client = get_vc3_client()
    projects = vc3_client.listProjects()

    # Grab allocation by name
    allocation = vc3_client.getAllocation(allocationname=name)
    # Scan through and remove allocations from any projects
    for project in projects:
        if allocation.name in project.allocations:
            vc3_client.removeAllocationFromProject(
                allocation=allocation.name, projectname=project.name)
    # Finally delete allocation entity
    vc3_client.deleteAllocation(allocationname=allocation.name)

    flash('Allocation has been successfully removed from any projects and deleted', 'success')

    return redirect(url_for('list_allocations'))


@app.route('/resource', methods=['GET'])
@authenticated
def list_resources():
    """ Route for HPC and Resources List View """
    vc3_client = get_vc3_client()
    resources = vc3_client.listResources()

    return render_template('resource.html', resources=resources)


@app.route('/resource/<name>', methods=['GET'])
@authenticated
def view_resource(name):
    """
    Route to view specific Resource profiles

    :param name: name attribute of Resource to view
    :return: Directs to detailed profile view of said Resource
    """
    vc3_client = get_vc3_client()
    resources = vc3_client.listResources()

    for resource in resources:
        if resource.name == name:
            resourcename = resource.name
            owner = resource.owner
            accessflavor = resource.accessflavor
            description = resource.description
            displayname = resource.displayname
            url = resource.url
            docurl = resource.docurl
            organization = resource.organization

            return render_template('resource_profile.html', name=resourcename,
                                   owner=owner, accessflavor=accessflavor,
                                   resource=resource, description=description,
                                   displayname=displayname, url=url,
                                   docurl=docurl, organization=organization)
    app.logger.error("Could not find Resource when viewing: {0}".format(name))
    raise LookupError('resource')


@app.route('/admin', methods=['GET'])
@authenticated
def admin():
    """ List View of All Virtual Clusters """
    if session['primary_identity'] in ['c4686d14-d274-11e5-b866-0febeb7fd79e',
                                       'c3b990a0-d274-11e5-b641-934c1e30fc08',
                                       'f1f26455-cbd5-4933-986b-47c57ee20987',
                                       'be58c8e2-fc13-11e5-82f7-f7141a8b0c16',
                                       'f79bc072-c1f4-412f-a813-00ff11760062',
                                       '05e05adf-e9d4-487f-8771-b6b8a25e84d3',
                                       'a877729e-d274-11e5-a5d2-2f448d5a1c26',
                                       'c887eb90-d274-11e5-bf28-779c8998e810',
                                       'c456b77c-d274-11e5-b82c-23a245a48997',
                                       'c444a294-d274-11e5-b7f1-e3782ed16687']:
        vc3_client = get_vc3_client()
        vc3_requests = vc3_client.listRequests()
        nodesets = vc3_client.listNodesets()
        clusters = vc3_client.listClusters
        request_list = []

        for vc3_request in vc3_requests:
            request_list.append(str(vc3_request.name))

        return render_template('admin.html', requests=vc3_requests,
                               nodesets=nodesets, clusters=clusters,
                               requestlist=request_list)
    else:
        return redirect(url_for('errorpage'))


@app.route('/request', methods=['GET'])
@authenticated
def list_requests():
    """ List View of Virtual Clusters """
    vc3_client = get_vc3_client()
    vc3_requests = vc3_client.listRequests()
    nodesets = vc3_client.listNodesets()
    clusters = vc3_client.listClusters
    request_list = []

    for vc3_request in vc3_requests:
        if vc3_request.owner == session['name']:
            request_list.append(str(vc3_request.name))

        headnode = None
        if vc3_request.headnode:
            try:
                headnode = vc3_client.getNodeset(vc3_request.headnode)
            except:
                pass
        # use headnode structure in the profile.
        vc3_request.headnode = headnode

    return render_template('request.html', requests=vc3_requests,
                           nodesets=nodesets, clusters=clusters,
                           requestlist=request_list)


@app.route('/request/new', methods=['GET', 'POST'])
@authenticated
@project_exists
def create_request():
    """
    Form to launch new Virtual Cluster

    Users must have both, a validated allocation and cluster template to launch
    """
    vc3_client = get_vc3_client()
    if request.method == 'GET':
        allocations = vc3_client.listAllocations()
        clusters = vc3_client.listClusters()
        projects = vc3_client.listProjects()
        environments = vc3_client.listEnvironments()
        return render_template('request_new.html', allocations=allocations,
                               clusters=clusters, projects=projects,
                               environments=environments)

    elif request.method == 'POST':
        # Define and store new Virtual Clusters within infoservice
        # Policies currently default to "static-balanced"
        # Environments currently default to "condor-glidein-password-env1"
        # Return redirects to Virtual Clusters List View after creation
        allocations = []
        environments = []

        inputname = request.form['name']
        owner = session['name']
        expiration = None
        cluster = request.form['cluster']
        project = request.form['project']
        policy = "static-balanced"
        translatename = "".join(inputname.split())
        vc3requestname = translatename.lower()
        description_input = request.form['description']
        description = str(description_input)

        for selected_environment in request.form.getlist('environment'):
            environments.append(selected_environment)

        for selected_allocation in request.form.getlist('allocation'):
            allocations.append(selected_allocation)

        try:
            newrequest = vc3_client.defineRequest(name=vc3requestname,
                                                  owner=owner, cluster=cluster,
                                                  project=project,
                                                  allocations=allocations,
                                                  environments=environments,
                                                  policy=policy,
                                                  expiration=expiration,
                                                  description=description)
            vc3_client.storeRequest(newrequest)
        except:
            owner = session['name']
            cluster = request.form['cluster']
            environment = request.form['environment']
            project = request.form['project']
            policy = "static-balanced"
            description_input = request.form['description']
            description = str(description_input)

            allocations = vc3_client.listAllocations()
            clusters = vc3_client.listClusters()
            projects = vc3_client.listProjects()
            environments = vc3_client.listEnvironments()
            flash('You have already launched a Virtual Cluster with that name.'
                  'Please choose a different name.', 'warning')
            return render_template('request_new.html', cluster=cluster,
                                   clusters=clusters, environments=environments,
                                   project=project, projects=projects,
                                   description=description, environment=environment, allocations=allocations)

        flash('Your Virtual Cluster has been successfully launched.', 'success')

        return redirect(url_for('list_requests'))


@app.route('/request/<name>', methods=['GET', 'POST'])
@authenticated
def view_request(name):
    """
    Route for specific detailed page view of Virtual Clusters

    :param name: name attribute of Virtual Cluster
    :return: Directs to detailed page view of Virtual Clusters with
    associated attributes
    """
    # Checks if user is member of project associated with Virtual Cluster
    member_in_vc = project_in_vc(name=name)
    if member_in_vc is False:
        flash('You do not appear to be have access to view this Virtual Cluster'
              'Please contact owner to request membership.', 'warning')
        return redirect(url_for('list_requests'))

    vc3_client = get_vc3_client()
    vc3_requests = vc3_client.listRequests()
    nodesets = vc3_client.listNodesets()
    clusters = vc3_client.listClusters
    users = vc3_client.listUsers()
    vc3_request = None
    allocations = vc3_client.listAllocations()

    if request.method == 'GET':
        vc3_request = vc3_client.getRequest(requestname=name)
        if vc3_request:
            requestname = vc3_request.name
            owner = vc3_request.owner
            action = vc3_request.action
            state = vc3_request.state
            vc3allocations = vc3_request.allocations
            description = vc3_request.description
            project = vc3_request.project

            headnode = None
            if vc3_request.headnode:
                try:
                    headnode = vc3_client.getNodeset(vc3_request.headnode)
                except:
                    # The headnode may have been cleaned-up already, or maybe
                    # it was never created.
                    pass

            # use headnode structure in the profile.
            vc3_request.headnode = headnode

            for user in users:
                if user.name == owner:
                    profile = user

            return render_template('request_profile.html', name=requestname,
                                   owner=owner, requests=vc3_requests,
                                   clusters=clusters, nodesets=nodesets,
                                   action=action, state=state, users=users,
                                   vc3allocations=vc3allocations, project=project,
                                   allocations=allocations, description=description,
                                   profile=profile, vc3_request=vc3_request)
        app.logger.error("Could not find VC when viewing: {0}".format(name))
        raise LookupError('virtual cluster')

    elif request.method == 'POST':
        # Method to terminate running a specific Virtual Cluster
        # based on name argument that is passed through
        for vc3_request in vc3_requests:
            if vc3_request.name == name:
                requestname = vc3_request.name

                vc3_client.terminateRequest(requestname=requestname)

                flash('Your Virtual Cluster has successfully begun termination.',
                      'success')
                return redirect(url_for('list_requests'))
        flash('Could not find specified Virtual Cluster', 'warning')
        app.logger.error("Could not find VC when terminating: {0}".format(name))
        return redirect(url_for('list_requests'))


@app.route('/request/edit/<name>', methods=['GET', 'POST'])
@authenticated
def edit_request(name):
    """
    Route to edit specific Virtual Clusters

    :param name: name attribute of Virtual Cluster
    :return: Directs to detailed page view of Virtual Clusters with updated
    associated attributes
    """
    vc3_client = get_vc3_client()
    if request.method == 'GET':
        vc3_request = vc3_client.getRequest(requestname=name)
        return render_template('request_edit.html', request=vc3_request, name=name)

    elif request.method == 'POST':
        vc3_request = None
        vc3_request = vc3_client.getRequest(requestname=name)
        if vc3_request:
            vc3_request.description = request.form['description']
            # vc3_request.displayname = request.form['displayname']

            vc3_client.storeRequest(vc3_request)
        return redirect(url_for('view_request', name=name))


@app.route('/request/delete/<name>', methods=['GET'])
@authenticated
def delete_virtualcluster(name):
    """
    Route for method to delete Virtual Cluster

    :param name: name attribute of Virtual Cluster to delete
    :return: Redirect to List Virtual Clusters page with VC deleted
    """
    vc3_client = get_vc3_client()

    # Grab VC by name and delete entity

    vc = vc3_client.getRequest(requestname=name)
    vc3_client.deleteRequest(requestname=vc.name)
    flash('Virtual Cluster has been successfully deleted', 'success')

    return redirect(url_for('list_requests'))


@app.route('/monitoring', methods=['GET'])
@authenticated
def dashboard():
    return render_template('dashboard.html')


@app.route('/environments', methods=['GET'])
@authenticated
def list_environments():
    """ List View of Environments """
    vc3_client = get_vc3_client()
    environments = vc3_client.listEnvironments()
    # Call list of build recipes from vc3-builder
    recipes = subprocess.check_output(["vc3-builder", "--list"])
    recipe_list = recipes.split()

    return render_template('environments.html', recipes=recipe_list,
                           environments=environments)


@app.route('/environments/new', methods=['GET', 'POST'])
@authenticated
def create_environment():
    """ New Environment Creation Form """
    vc3_client = get_vc3_client()
    recipes = subprocess.check_output(["/usr/bin/vc3-builder", "--list"])
    recipe_list = recipes.split()

    if request.method == 'GET':
        environments = vc3_client.listEnvironments()
        return render_template('environment_new_2.html',
                               environments=environments, recipes=recipe_list)

    elif request.method == 'POST':
        # Gathering and storing information from new allocation form
        # into info-service
        # Description from text input stored as string to avoid malicious input

        displayname = request.form['name']
        owner = session['name']
        name = owner + '-' + displayname.lower()
        # packagelist = []
        envmap = {}
        files = {}
        description_input = request.form['description']
        description = str(description_input)
        packagelist = request.form.getlist('packagelist')

        try:
            new_environment = vc3_client.defineEnvironment(
                name=name, owner=owner, packagelist=packagelist,
                envmap=envmap, files=files,
                displayname=displayname, description=description)
            vc3_client.storeEnvironment(new_environment)
        except:
            name = request.form['name']
            description_input = request.form['description']
            description = str(description_input)
            environments = vc3_client.listEnvironments()
            flash('You have already created an environment with that name.', 'warning')
            return render_template('environment_new_2.html', name=name,
                                   packagelist=packagelist,
                                   description=description, environments=environments)

        flash('Successfully created a new environment', 'success')

        return redirect(url_for('list_environments'))


@app.route('/timeline', methods=['GET'])
@authenticated
def timeline():
    return render_template('timeline.html')


@app.route('/error', methods=['GET'])
@authenticated
def errorpage():

    if request.method == 'GET':
        return render_template('error.html')
