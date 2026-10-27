from django.urls import path
from rest_framework.authtoken.views import obtain_auth_token
from . import views, agent_views

urlpatterns = [
    path("register/", views.register),
    path("login/", obtain_auth_token),
    path("documents/", views.documents),
    path("documents/<int:doc_id>/", views.delete_doc),
    path("chat/", views.chat),
    path("conversations/", views.conversations),
    path("conversations/<int:conv_id>/", views.conversation_detail),
    path("summarize/", views.summarize),
    path("mcqs/", views.mcqs),
    path("agent/", agent_views.agent_run),
    path("agent/adapt/", agent_views.agent_adapt),
]