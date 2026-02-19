from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ArenaRunDetailView, ArenaRunsView, ArenaSimulateView, GameViewSet, AIOptionsView

router = DefaultRouter()
router.register(r'games', GameViewSet)

urlpatterns = [
    path('ai/options/', AIOptionsView.as_view(), name='ai-options'),
    path('arena/simulate/', ArenaSimulateView.as_view(), name='arena-simulate'),
    path('arena/runs/', ArenaRunsView.as_view(), name='arena-runs'),
    path('arena/runs/<int:run_id>/', ArenaRunDetailView.as_view(), name='arena-run-detail'),
    path('', include(router.urls)),
]
