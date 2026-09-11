from target_app import create_app


def test_app_shell_exposes_named_workspace_frame() -> None:
    client = create_app(testing=True).test_client()

    response = client.get("/app")

    assert response.status_code == 200
    assert b'name="memberWorkspace"' in response.data
    assert b'src="/workspace/search"' in response.data


def test_search_page_matches_the_artifact_contract() -> None:
    client = create_app(testing=True).test_client()

    response = client.get("/workspace/search")

    assert response.status_code == 200
    assert b"<h1>Member Search</h1>" in response.data
    assert b'<label for="f_003">Member ID</label>' in response.data
    assert b'name="f_003"' in response.data
    assert b'name="member-search"' in response.data
    assert b">Search</a>" in response.data
    assert b"aria-" not in response.data
    assert b"data-testid" not in response.data


def test_known_member_appears_in_search_results() -> None:
    client = create_app(testing=True).test_client()

    response = client.get("/workspace/results?f_003=00123")

    assert response.status_code == 200
    assert b"<h1>Member Search Results</h1>" in response.data
    assert b"00123" in response.data
    assert b"Avery Example" in response.data
    assert b'href="/workspace/member/00123"' in response.data
    assert b">View details</a>" in response.data


def test_unknown_member_is_a_visible_business_outcome() -> None:
    client = create_app(testing=True).test_client()

    response = client.get("/workspace/results?f_003=99999")

    assert response.status_code == 200
    assert b"No matching member" in response.data
    assert b"View details" not in response.data


def test_member_detail_contains_relational_account_data() -> None:
    client = create_app(testing=True).test_client()

    response = client.get("/workspace/member/00123")

    assert response.status_code == 200
    assert b"<h1>Member Details</h1>" in response.data
    assert b'name="member-details"' in response.data
    assert b"Member ID" in response.data
    assert b"00123" in response.data
    assert b'name="accounts"' in response.data
    assert b"Account type" in response.data
    assert b"Current balance" in response.data
    assert b"Savings" in response.data
    assert b"$1,250.50" in response.data
